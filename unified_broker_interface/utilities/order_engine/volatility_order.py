"""An option order priced from an implied volatility instead of a premium."""

import datetime
import decimal
import math
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)
from unified_broker_interface.utilities.order_engine.underlying_peg import (
    UnderlyingPeg,
)
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)

EXPIRES_AT = datetime.time(15, 30)
SECONDS_IN_A_YEAR = 365 * 24 * 60 * 60
HIGHEST_VOLATILITY_PERCENT = 500


class VolatilityOrder(UnderlyingPeg):
    """An option limit order whose price is the premium a stated implied volatility gives, kept current as the underlying and time move (the Atlas's G7).

    "Buy this call at 12.5 volatility" is how an options trader often thinks, because a premium goes stale the moment the underlying moves and a volatility does not. The engine turns the volatility into a premium with the Black-76 model, using the watched instrument as the forward, the option's own strike and expiry from the catalogue, and `interest_rate`. It re-prices on each tick as the underlying moves and expiry comes closer, through the same step and throttle as the underlying peg.

    Black-76 wants a forward price. When the watched instrument is a future it is used as the forward directly; otherwise, such as for the index itself, the forward is the spot grown by the interest rate to expiry.

    The order's own `price` is the worst it will accept: the most a buy pays and the least a sell takes. The model's premium is used whenever it is better than that. A caller who changes the price re-anchors the order at the volatility the new price implies.
    """

    SYNTHETIC_TYPE = 'volatility'

    def read_volatility(self):
        """The volatility the order is priced at, as a fraction.

        Returns:
            float: The volatility, such as 0.125 for 12.5 per cent.

        Raises:
            RefusedRequestError: With HTTP 400 when `volatility` is missing or is not a percentage above zero and at most 500.
        """
        value = self.number('volatility', True)
        if value <= 0 or value > HIGHEST_VOLATILITY_PERCENT:
            raise RefusedRequestError.refusal(
                f'volatility is a percentage above zero and at most '
                f'{HIGHEST_VOLATILITY_PERCENT}, not {value}',
                400,
            )
        return float(value) / 100

    def read_interest_rate(self):
        """The interest rate the model discounts at, as a fraction.

        Returns:
            float: The rate, 0 when the caller gave none.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number.
        """
        value = self.number('interest_rate', False)
        if value is None:
            return 0.0
        return float(value) / 100

    def remember_option(self, underlying):
        """Reads the option's strike, expiry and kind, and whether the watched instrument is a forward, and keeps them on the parent.

        Args:
            underlying (str): The watched instrument's id.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when the traded instrument is not an option with a strike and an expiry.
        """
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        identity = instrument.identity
        option_type = identity.get('option_type')
        strike = identity.get('strike_price')
        expiry = identity.get('expiry_date')
        if option_type not in ('CE', 'PE') or not strike or not expiry:
            raise RefusedRequestError.refusal(
                'a volatility order prices an option, and this instrument is '
                'not an option with a strike and an expiry',
                400,
                instrument_id=self.parent.instrument_id,
            )
        expiry_day = datetime.date.fromisoformat(str(expiry))
        expires = datetime.datetime.combine(
            expiry_day,
            EXPIRES_AT,
            moments.INDIA,
        )
        watched, _, _ = self.placement.market_context(underlying, False, False)
        shape = TradeableSegments.SHAPES.get(watched.bare_segment)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['strike_price'] = float(strike)
        self.parent.parameters['expires_at'] = expires.timestamp()
        self.parent.parameters['is_call'] = option_type == 'CE'
        self.parent.parameters['underlying_is_forward'] = shape == 'future'

    def model(self, underlying_price, now):
        """The Black-76 model for this option at one moment.

        Args:
            underlying_price (decimal.Decimal): The watched instrument's price.
            now (float): The Unix time.

        Returns:
            Black76 | None: The model, or None when the option has expired.
        """
        parameters = self.parent.parameters
        years = (parameters['expires_at'] - now) / SECONDS_IN_A_YEAR
        if years <= 0:
            return None
        rate = self.read_interest_rate()
        forward = float(underlying_price)
        if not parameters.get('underlying_is_forward'):
            forward = forward * math.exp(rate * years)
        return Black76(
            forward,
            parameters['strike_price'],
            years,
            rate,
            parameters['is_call'],
        )

    def premium_price(self, view, underlying_price, transaction_type, now):
        """The order price the stated volatility gives now, no worse than the caller's own price.

        Args:
            view (MarketView): The traded instrument's view, for rounding onto its tick.
            underlying_price (decimal.Decimal): The watched instrument's price.
            transaction_type (str): BUY or SELL.
            now (float): The Unix time.

        Returns:
            decimal.Decimal | None: The price, or None when the option has expired or the tick size is not known.
        """
        model = self.model(underlying_price, now)
        if model is None:
            return None
        premium = decimal.Decimal(str(round(model.price(self.read_volatility()), 6)))
        worst = self.read_order(self.parent.body).price
        if transaction_type == 'BUY':
            premium = min(premium, worst)
        else:
            premium = max(premium, worst)
        return self.bounded(premium, view, transaction_type)

    def run(self, intent, started_at):
        """Prices the option from the volatility and places it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a missing underlying or volatility, a bad range, step or rate, an instrument that is not an option, or an order that is not a LIMIT with a price, and 503 when the underlying's quote has no last price or the option has expired.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        underlying = self.underlying()
        self.read_volatility()
        self.read_interest_rate()
        self.read_range()
        self.read_step_ticks()
        if order.order_type != 'LIMIT' or order.price is None:
            raise RefusedRequestError.refusal(
                'a volatility order is a LIMIT whose price is the worst it '
                'will accept, so it needs order_type LIMIT and a price',
                400,
            )
        self.remember_option(underlying)

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(underlying, True, False)
        underlying_price = self.underlying_price({underlying: quote})
        if underlying_price is None:
            raise RefusedRequestError.refusal(
                'a volatility order is priced from the underlying, and its '
                'quote does not carry a last traded price yet',
                503,
                instrument_id=underlying,
            )
        price = self.premium_price(
            self.view({}),
            underlying_price,
            order.transaction_type,
            time.time(),
        )
        if price is None:
            raise RefusedRequestError.refusal(
                'the option has expired or has no agreed tick size, so no '
                'premium can be worked out for it',
                503,
                instrument_id=self.parent.instrument_id,
            )
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['underlying_start'] = str(underlying_price)
        self.record_received()
        self.save()
        body, status, _ = self.place_leg(
            'entry',
            self.priced(order, price),
            started_at,
        )
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        body['priced_at'] = str(price)
        return body, status

    def on_price_tick(self, quotes, now):
        """Re-prices the order from the volatility, once the price has moved at least a step.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was moved.
        """
        leg = self.working_leg()
        if leg is None or leg.price is None:
            return False
        underlying_price = self.underlying_price(quotes)
        tick_size = self.tick_size()
        if underlying_price is None or not tick_size:
            return False
        price = self.premium_price(
            self.view(quotes),
            underlying_price,
            leg.transaction_type,
            now,
        )
        if price is None:
            return False
        current = decimal.Decimal(str(leg.price))
        if abs(price - current) < tick_size * self.read_step_ticks():
            return False
        moved = self.reprice_leg(
            leg,
            price,
            None,
            f'at {self.parent.parameters.get("volatility")} volatility with '
            f'the underlying at {underlying_price}, the premium is {price}',
        )
        if moved:
            self.save()
        return moved

    def on_leg_modified(self, leg, before):
        """Takes the volatility the caller's new price implies, so the order is priced at that volatility from now on.

        Args:
            leg (OrderLeg): The leg, holding its new price.
            before (dict): What the leg held before, with `price`.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'entry' or leg.price is None or leg.price == before.get('price'):
            return
        underlying = self.underlying()
        try:
            _, quote, _ = self.placement.market_context(underlying, True, False)
        except RefusedRequestError as refusal:
            self.logger.warning(
                f'Parent {self.parent.parent_order_id} could not read the '
                f'underlying to re-anchor its volatility: '
                f'{refusal.body.get("error")}'
            )
            return
        underlying_price = self.underlying_price({underlying: quote})
        if underlying_price is None:
            return
        model = self.model(underlying_price, time.time())
        if model is None:
            return
        implied = model.implied_volatility(float(leg.price))
        if implied is None:
            return
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['volatility'] = round(implied * 100, 4)
        self.record_parameters(
            f'the caller moved the price to {leg.price}, which is '
            f'{self.parent.parameters["volatility"]} volatility'
        )
        self.save()
