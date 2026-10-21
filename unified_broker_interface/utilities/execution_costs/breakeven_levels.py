"""The three levels of a real breakeven stop for one position: the floor, the tripwire and the switch-on."""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.price_flicker import (
    DEFAULT_HORIZON_SECONDS,
    DEFAULT_PERCENTILE,
    PriceFlicker,
)
from unified_broker_interface.utilities.execution_costs.switch_on_price import (
    SwitchOnPrice,
)
from unified_broker_interface.utilities.execution_costs.tripwire_price import (
    TripwirePrice,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)

DERIVATIVE_SHAPES = [
    'future',
    'option',
]


class BreakevenLevelsError(Exception):
    """The levels of a position cannot be worked out, with the HTTP status that says why.

    Attributes:
        message (str): What is missing.
        status (int): The HTTP status to answer with.
    """

    def __init__(self, message, status):
        """Builds the error.

        Args:
            message (str): What is missing.
            status (int): The HTTP status.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(message)
        self.message = message
        self.status = status


class BreakevenLevels:
    """Works out a position's floor, tripwire and switch-on from the charge rates, the brokerage, the measured stop slip, the instrument's flicker and its live spread.

    A breakeven stop that never loses after costs needs three levels. The **floor** is the exit price at which the position makes exactly nothing after every tax, fee and brokerage (`BreakevenPrice`). The **tripwire** is the trigger the stop should use, beyond the floor by the slip such stops show (`TripwirePrice`). The **switch-on** is how far the watched price must go beyond the tripwire before the stop is moved there, so that ordinary flicker does not fire it at once (`SwitchOnPrice`).

    The charge rates, the broker costs and the stop slips change at most once a day, so they are read on the first request of each day in India and kept. The flicker is read from the instrument's stored ticks on every request.

    Attributes:
        charge_rate_table (ChargeRateTable): The statutory charge rates.
        cost_table (BrokerCostTable): Each broker's brokerage.
        allowance (StopSlipAllowance): The measured stop slips.
        connect (Callable): Opens a PostgreSQL connection, such as `configurations.get_postgres`.
        loaded_on (datetime.date | None): The day in India the three tables were last read, or None before the first read.
    """

    def __init__(self, charge_rate_table, cost_table, allowance, connect):
        """Builds the levels service.

        Args:
            charge_rate_table (ChargeRateTable): The charge rates.
            cost_table (BrokerCostTable): The broker costs.
            allowance (StopSlipAllowance): The stop slips.
            connect (Callable): Opens a PostgreSQL connection.

        Returns:
            None: This method returns nothing.
        """
        self.charge_rate_table = charge_rate_table
        self.cost_table = cost_table
        self.allowance = allowance
        self.connect = connect
        self.loaded_on = None

    def refresh(self, now):
        """Reads the charge rates, broker costs and stop slips again when the day in India has changed since they were last read.

        Args:
            now (datetime.datetime): The current moment.

        Returns:
            bool: True when they were read.

        Raises:
            psycopg2.Error: When the database cannot be read.
            ValueError: When the broker cost table is empty.
        """
        today = now.astimezone(INDIA).date()
        if self.loaded_on == today:
            return False
        self.charge_rate_table.load()
        self.cost_table.load()
        self.allowance.read(self.connect, now)
        self.loaded_on = today
        return True

    def cheapest_broker(self, category):
        """The broker charging least for a category, the first by name among equals, as the lowest-cost selector prefers when no broker is busy.

        Args:
            category (str): `delivery`, `fno` or `intraday`.

        Returns:
            str | None: The broker's name, or None when the cost table is empty.
        """
        best = None
        best_fee = None
        for broker_name in sorted(self.cost_table.rows):
            fee = self.cost_table.rows[broker_name].fee(category)
            if best is None or fee < best_fee:
                best = broker_name
                best_fee = fee
        return best

    def spread(self, quote):
        """The gap between the best bid and the best ask of a quote document.

        Args:
            quote (dict | None): The unified quote document, with `depth` holding `buy` and `sell` levels.

        Returns:
            decimal.Decimal | None: The spread, or None when either side is empty or there is no quote.
        """
        if not quote:
            return None
        depth = quote.get('depth') or {}
        buys = depth.get('buy') or []
        sells = depth.get('sell') or []
        if not buys or not sells:
            return None
        best_bid = buys[0].get('price')
        best_ask = sells[0].get('price')
        if not best_bid or not best_ask:
            return None
        return decimal.Decimal(str(best_ask)) - decimal.Decimal(str(best_bid))

    def levels(
        self,
        details,
        quote,
        entry_price,
        quantity,
        opening_side='BUY',
        product='NRML',
        broker=None,
        percentile=DEFAULT_PERCENTILE,
        horizon_seconds=DEFAULT_HORIZON_SECONDS,
        now=None,
    ):
        """Works out the three levels of one position.

        Args:
            details (dict): The instrument's details as `/api/instruments/details` answers them, with `instrument_id`, `segment`, `shape` and `tick_size`.
            quote (dict | None): Its unified quote document, or None when there is none.
            entry_price (decimal.Decimal): The average price the position was opened at.
            quantity (int): The position's size, in units.
            opening_side (str): `BUY` or `SELL`, the side that opened the position.
            product (str): The product, such as `NRML`, `MIS` or `CNC`.
            broker (str | None): The broker the orders go to, or None for the cheapest.
            percentile (int): The percentile of the stop slips and of the flicker to allow for.
            horizon_seconds (int): How far ahead the flicker is measured.
            now (datetime.datetime | None): The current moment, or None for now.

        Returns:
            dict: The answer, with `floor`, `tripwire` and `switch_on`, each a dict with its `price` as text and how it was worked out; `tripwire` and `switch_on` are None when neither a measured figure nor a spread is known.

        Raises:
            BreakevenLevelsError: When the segment's charges or the broker's costs are not known.
            psycopg2.Error: When the database cannot be read.
        """
        now = now or datetime.datetime.now(INDIA)
        self.refresh(now)
        segment = details.get('segment')
        if details.get('shape') in DERIVATIVE_SHAPES:
            instrument_kind = 'derivative'
        else:
            instrument_kind = 'security'
        category = self.charge_rate_table.category(instrument_kind, product)
        charge_rate = self.charge_rate_table.rate(segment, category)
        if charge_rate is None:
            raise BreakevenLevelsError(f'The taxes and fees of {segment} {category} trades are not known; add a row to unified.charge_rates.', 409)
        broker = broker or self.cheapest_broker(category)
        costs = self.cost_table.costs(broker)
        if costs is None:
            raise BreakevenLevelsError(f'The brokerage of {broker} is not known; add a row to unified.broker_order_costs.', 409)
        brokerage = costs.fee(category)
        tick_size = details.get('tick_size')
        if tick_size is not None:
            tick_size = decimal.Decimal(str(tick_size))
        breakeven = BreakevenPrice(charge_rate, opening_side, entry_price, quantity, brokerage, tick_size)
        spread = self.spread(quote)
        if opening_side == 'BUY':
            stop_side = 'SELL'
        else:
            stop_side = 'BUY'
        slip_fraction = self.allowance.fraction(segment, stop_side, percentile)
        tripwire = None
        if slip_fraction is not None or spread is not None:
            tripwire = TripwirePrice(breakeven, slip_fraction, spread)
        flicker = PriceFlicker(opening_side, horizon_seconds)
        flicker.read(self.connect, str(details['instrument_id']), now)
        flicker_distance = flicker.distance(percentile)
        switch_on = None
        if tripwire is not None and (flicker_distance is not None or spread is not None):
            switch_on = SwitchOnPrice(tripwire, flicker_distance, spread)
        return self.answer(details, breakeven, tripwire, switch_on, flicker, spread, category, broker, percentile, charge_rate)

    def text(self, value):
        """A decimal as text, so that JSON keeps every digit.

        Args:
            value (decimal.Decimal | None): The value.

        Returns:
            str | None: The value as text, or None.
        """
        if value is None:
            return None
        return str(value)

    def answer(self, details, breakeven, tripwire, switch_on, flicker, spread, category, broker, percentile, charge_rate):
        """Builds the answer of `levels`.

        Args:
            details (dict): The instrument's details.
            breakeven (BreakevenPrice): The floor.
            tripwire (TripwirePrice | None): The tripwire, or None.
            switch_on (SwitchOnPrice | None): The switch-on, or None.
            flicker (PriceFlicker): The flicker, with its samples read.
            spread (decimal.Decimal | None): The live spread.
            category (str): The charge category.
            broker (str): The broker.
            percentile (int): The percentile allowed for.
            charge_rate (ChargeRate): The charge rates used.

        Returns:
            dict: The answer.
        """
        segment = details.get('segment')
        stop_side = 'SELL' if breakeven.opening_side == 'BUY' else 'BUY'
        checked_on = charge_rate.checked_on.isoformat() if charge_rate.checked_on else None
        floor = {
            'price': self.text(breakeven.price()),
            'exact_price': self.text(breakeven.exact_price()),
            'distance_from_entry': self.text(breakeven.distance()),
            'charges_checked_on': checked_on,
        }
        tripwire_answer = None
        if tripwire is not None:
            tripwire_answer = {
                'price': self.text(tripwire.price()),
                'distance_from_entry': self.text(tripwire.distance_from_entry()),
                'source': tripwire.source(),
                'slip_basis_points': self.text(self.allowance.basis_points(segment, stop_side, percentile)),
                'stops_measured': self.allowance.stop_count(segment, stop_side),
            }
        switch_on_answer = None
        if switch_on is not None:
            switch_on_answer = {
                'price': self.text(switch_on.price()),
                'distance_from_entry': self.text(switch_on.distance_from_entry()),
                'source': switch_on.source(),
                'flicker': self.text(switch_on.flicker),
                'ticks_measured': len(flicker.moves()),
                'horizon_seconds': flicker.horizon_seconds,
            }
        return {
            'instrument_id': str(details['instrument_id']),
            'segment': segment,
            'category': category,
            'broker': broker,
            'brokerage_per_order': self.text(breakeven.brokerage_per_order),
            'opening_side': breakeven.opening_side,
            'entry_price': self.text(breakeven.entry_price),
            'quantity': breakeven.quantity,
            'tick_size': self.text(breakeven.tick_size),
            'spread': self.text(spread),
            'percentile': percentile,
            'floor': floor,
            'tripwire': tripwire_answer,
            'switch_on': switch_on_answer,
        }
