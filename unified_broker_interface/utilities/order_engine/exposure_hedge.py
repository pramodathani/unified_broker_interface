"""A hedge placed when the account's net exposure leaves the band it was meant to stay in."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

DEFAULT_BUFFER_TICKS = 2


class ExposureHedge(SyntheticOrder):
    """Watches the net exposure of a set of positions and trades a hedge when it leaves a band.

    A book of options that was delta neutral this morning is not delta neutral by lunchtime, because the market moved and every option's sensitivity moved with it. The usual answer is to buy or sell the underlying future until the total is back near zero. The same shape covers plainer cases: a portfolio that is meant to stay roughly market neutral, or a position whose size is meant to stay inside a limit.

    **This works in exposure, not in greeks, and that is a real limitation stated rather than hidden.** The engine has no option pricing model and no implied volatility, so it cannot compute a delta. What it can do is take a number per unit from the caller — `exposure_per_unit` on each watched instrument — multiply it by the position actually held, and add them up. Passing 1 makes that a plain signed quantity. Passing a delta computed somewhere else makes it a delta hedge, recalculated against live positions on every tick, which is what most people running one actually want: the greeks come from their own model and the arithmetic and the order come from here.

    The positions are the account's own, read from `unified:portfolio:positions`, rather than only the legs this parent placed. That is the point — a hedge is about what the account is holding, however it came to hold it.

    `lower_band` and `upper_band` are where it acts. Inside them nothing happens, however long it sits there. Outside them, a hedge is sent on `hedge_instrument_id`, sized to bring the total back to the middle of the band, and the band is what stops it trading on every tick: a band of zero would send an order every time a price moved a paisa.

    A hedge that has been sent counts towards the exposure straight away, before the account's position document has caught up with it. Otherwise the same hedge is sent again on the next tick and every tick after it until the fill is polled, which is several seconds, by which time the account is hedged several times over in the wrong direction.
    """

    SYNTHETIC_TYPE = 'exposure_hedge'
    WANTS_PRICES = True

    def read_watched(self):
        """The instruments whose positions count towards the exposure, and what each unit is worth.

        Returns:
            dict: Instrument ids to exposure per unit, as `decimal.Decimal`.

        Raises:
            RefusedRequestError: With HTTP 400 when the list is missing or an entry cannot be read.
        """
        given = self.parent.parameters.get('watched')
        if not isinstance(given, list) or not given:
            raise RefusedRequestError.refusal(
                'an exposure hedge needs watched, a list of the instruments '
                'whose positions count, each with its exposure_per_unit',
                400,
            )
        watched = {}
        for position, entry in enumerate(given):
            if not isinstance(entry, dict):
                raise RefusedRequestError.refusal(
                    f'watched entry {position + 1} must be an object, not '
                    f'{type(entry).__name__}',
                    400,
                )
            instrument_id = entry.get('instrument_id')
            if not instrument_id:
                raise RefusedRequestError.refusal(
                    f'watched entry {position + 1} must name its '
                    'instrument_id',
                    400,
                )
            watched[instrument_id] = self.number(
                entry.get('exposure_per_unit', 1),
                f'watched entry {position + 1} exposure_per_unit',
            )
        return watched

    def read_band(self):
        """The range the exposure is allowed to sit in.

        Returns:
            tuple: The lower and upper bounds as `decimal.Decimal`.

        Raises:
            RefusedRequestError: With HTTP 400 when either is missing or the lower is not below the upper.
        """
        lower = self.parent.parameters.get('lower_band')
        upper = self.parent.parameters.get('upper_band')
        if lower is None or upper is None:
            raise RefusedRequestError.refusal(
                'an exposure hedge needs lower_band and upper_band, the range '
                'the exposure is allowed to sit in',
                400,
            )
        lower = self.number(lower, 'lower_band')
        upper = self.number(upper, 'upper_band')
        if lower >= upper:
            raise RefusedRequestError.refusal(
                f'lower_band of {lower} is not below upper_band of {upper}',
                400,
            )
        return lower, upper

    def read_hedge(self):
        """The instrument the hedge is traded in, and what one unit of it is worth.

        Returns:
            tuple: The instrument id (str) and its exposure per unit (decimal.Decimal).

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or its exposure is zero.
        """
        instrument_id = self.parent.parameters.get('hedge_instrument_id')
        if not instrument_id:
            raise RefusedRequestError.refusal(
                'an exposure hedge needs hedge_instrument_id, the instrument '
                'it trades to bring the exposure back',
                400,
            )
        per_unit = self.number(
            self.parent.parameters.get('hedge_exposure_per_unit', 1),
            'hedge_exposure_per_unit',
        )
        if per_unit == 0:
            raise RefusedRequestError.refusal(
                'hedge_exposure_per_unit cannot be zero: an instrument with '
                'no exposure per unit cannot hedge anything',
                400,
            )
        return instrument_id, per_unit

    def number(self, value, name):
        """One of the caller's numbers.

        Args:
            value (object): The value.
            name (str): Its name, for the message.

        Returns:
            decimal.Decimal: The number.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a finite number.
        """
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )
        if not number.is_finite():
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )
        return number

    def run(self, intent, started_at):
        """Records the watch and sends nothing, because nothing is out of band yet.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the watch cannot be read, and 503 when the hedge instrument has no agreed tick size.
        """
        order = self.read_order(self.parent.body)
        self.read_watched()
        lower, upper = self.read_band()
        hedge_instrument, _ = self.read_hedge()

        if order.dry_run:
            prepared = self.placement.prepare(order, hedge_instrument)
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.save()
        return {
            'broker': None,
            'instrument_id': hedge_instrument,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'armed',
            'order_id': None,
            'lower_band': str(lower),
            'upper_band': str(upper),
            'status_message': (
                'the exposure is being watched and a hedge will be sent if it '
                f'leaves {lower} to {upper}'
            ),
            'skipped': [],
        }, 202

    def held(self, positions, instrument_id):
        """How much of one instrument the account is holding, signed.

        `unified:portfolio:positions` is a JSON document with a `net` list rather than a hash, so a lookup means walking it. Quantities are signed, positive for a long.

        Args:
            positions (dict | None): The positions document.
            instrument_id (str): The instrument to find.

        Returns:
            decimal.Decimal: The net quantity, zero when there is no position.
        """
        if not isinstance(positions, dict):
            return decimal.Decimal('0')
        total = decimal.Decimal('0')
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict):
                continue
            if entry.get('instrument_id') != instrument_id:
                continue
            try:
                total = total + decimal.Decimal(str(entry.get('quantity', 0)))
            except (decimal.InvalidOperation, TypeError, ValueError):
                continue
        return total

    def exposure(self, positions):
        """The total exposure of everything being watched, counting hedges already sent.

        Args:
            positions (dict | None): The positions document.

        Returns:
            decimal.Decimal: The total.
        """
        total = decimal.Decimal('0')
        for instrument_id, per_unit in self.read_watched().items():
            total = total + self.held(positions, instrument_id) * per_unit
        return total + self.hedges_in_flight()

    def hedges_in_flight(self):
        """The exposure of hedges this parent has sent but that the position document has not caught up with.

        Without this the hedge fires again on every tick until the first one fills and the positions are polled, which is several seconds, and by then the account is hedged several times over in the wrong direction. The offline scenario showed it immediately: one position out of band, two identical hedges on two consecutive ticks.

        A leg that was rejected or cancelled is not counted, because nothing came of it. A leg that filled is counted here **and** will appear in the positions document once it is polled, which double counts it for the few seconds in between. That is the conservative direction — it makes the hedge look more complete than it is, so the engine waits rather than hedging twice — and it settles as soon as the positions catch up.

        Returns:
            decimal.Decimal: The exposure already on its way.
        """
        _, per_unit = self.read_hedge()
        total = decimal.Decimal('0')
        for leg in self.parent.legs:
            if leg.role != 'hedge':
                continue
            if leg.state in ('rejected', 'cancelled'):
                continue
            quantity = decimal.Decimal(str(leg.quantity or 0))
            if leg.transaction_type == 'SELL':
                quantity = -quantity
            total = total + quantity * per_unit
        return total

    def on_price_tick(self, quotes, now):
        """Sends a hedge when the exposure has left its band.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a hedge was sent.
        """
        lower, upper = self.read_band()
        hedge_instrument, per_unit = self.read_hedge()
        _, _, positions = self.placement.market_context(
            self.parent.instrument_id,
            False,
            True,
        )
        total = self.exposure(positions)
        if lower <= total <= upper:
            return False

        middle = (lower + upper) / 2
        wanted = (middle - total) / per_unit
        quantity = int(abs(wanted))
        if quantity < 1:
            return False
        side = 'BUY' if wanted > 0 else 'SELL'
        view = self.view(quotes, hedge_instrument)
        price = self.hedge_price(view, side)
        if price is None:
            return False
        return self.send_hedge(
            hedge_instrument,
            side,
            quantity,
            price,
            total,
        )

    def hedge_price(self, view, side):
        """The price the hedge goes out at, past the touch so that it trades now.

        Args:
            view (MarketView): The hedge instrument's quote.
            side (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when the book gives nothing to price against.
        """
        touch = view.opposite_touch(side)
        if touch is None:
            touch = view.last()
        if touch is None:
            return None
        price = view.moved(touch, DEFAULT_BUFFER_TICKS, side, True)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        return price

    def send_hedge(self, instrument_id, side, quantity, price, total):
        """Sends the hedge and records why.

        Args:
            instrument_id (str): The instrument to trade.
            side (str): BUY or SELL.
            quantity (int): How much.
            price (decimal.Decimal): The limit price.
            total (decimal.Decimal): The exposure that triggered it, for the message.

        Returns:
            bool: True, because a hedge was sent whatever the broker then said.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('synthetic', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = quantity
        body['transaction_type'] = side
        body['price'] = str(price)
        answer, _, _ = self.place_leg(
            'hedge',
            self.read_order(body),
            None,
            self.chosen_broker(),
            instrument_id,
        )
        if self.parent.state == 'received':
            outcome = answer.get('outcome')
            self.record_state(
                'working' if outcome == 'accepted' else 'failed',
                f'the exposure reached {total}, so a hedge went out',
            )
        self.save()
        return True
