"""A resting limit order whose price moves with another instrument, usually an option's underlying."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.peg import Peg


class UnderlyingPeg(Peg):
    """A limit order re-priced by how far another instrument has moved since it was placed (the Atlas's G6).

    The price is the caller's limit plus `delta` times the watched instrument's move: `price = start price + delta × (underlying − underlying at start)`. For a Nifty call with a delta of 0.5, a 40-point rise in the index raises the bid by 20. That keeps a resting option bid fair as the index moves, without reading the option's own book, which on a far strike is thin and jumps on a single order.

    `lowest_price` and `highest_price` bound it, and `step_ticks` is the smallest move worth a modify, because every modify costs a place in the queue and an order message. Like every peg it is throttled by `reprice_leg`.

    `watch_instrument_id` names the underlying, the same parameter `cross_instrument` uses, because the price ticker reads that name to know which extra quote to fetch. A caller who changes the leg's price re-anchors it: the new price and the underlying's price at that moment become the new starting point.
    """

    SYNTHETIC_TYPE = 'underlying_peg'

    def underlying(self):
        """The instrument whose moves the price follows.

        Returns:
            str: The instrument id.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is the traded instrument itself.
        """
        watched = self.parent.parameters.get('watch_instrument_id')
        if not watched:
            raise RefusedRequestError.refusal(
                'an underlying peg follows another instrument, so it needs '
                'watch_instrument_id',
                400,
            )
        if watched == self.parent.instrument_id:
            raise RefusedRequestError.refusal(
                'an underlying peg follows another instrument; to follow the '
                'traded instrument itself use peg',
                400,
            )
        return watched

    def number(self, name, required):
        """One numeric parameter.

        Args:
            name (str): The parameter's name.
            required (bool): Whether it must be given.

        Returns:
            decimal.Decimal | None: The number, or None when it was not given and is not required.

        Raises:
            RefusedRequestError: With HTTP 400 when it is required and missing, or is not a number.
        """
        value = self.parent.parameters.get(name)
        if value is None:
            if required:
                raise RefusedRequestError.refusal(
                    f'an underlying peg needs {name}',
                    400,
                )
            return None
        try:
            return decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )

    def read_range(self):
        """The prices the order is kept between.

        Returns:
            tuple: The lowest price and the highest price (decimal.Decimal | None each).

        Raises:
            RefusedRequestError: With HTTP 400 when either is not above zero, or the lowest is above the highest.
        """
        lowest = self.number('lowest_price', False)
        highest = self.number('highest_price', False)
        for name, value in (('lowest_price', lowest), ('highest_price', highest)):
            if value is not None and value <= 0:
                raise RefusedRequestError.refusal(
                    f'{name} must be above zero, not {value}',
                    400,
                )
        if lowest is not None and highest is not None and lowest > highest:
            raise RefusedRequestError.refusal(
                f'lowest_price {lowest} is above highest_price {highest}',
                400,
            )
        return lowest, highest

    def read_step_ticks(self):
        """How many ticks the price must move before the order is modified.

        Returns:
            int: The step, at least 1.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number of at least 1.
        """
        value = self.parent.parameters.get('step_ticks', 1)
        try:
            step = int(value)
        except (TypeError, ValueError):
            step = 0
        if step < 1:
            raise RefusedRequestError.refusal(
                f'step_ticks must be a whole number of at least 1, not {value!r}',
                400,
            )
        return step

    def underlying_price(self, quotes):
        """The underlying's last traded price, out of the quotes a tick carried.

        Args:
            quotes (dict): The quotes.

        Returns:
            decimal.Decimal | None: The price, or None when the quote does not carry it.
        """
        return self.view(quotes, self.underlying()).last()

    def target_price(self, view, underlying_price, transaction_type):
        """Where the order should be for the underlying's price now.

        Args:
            view (MarketView): The traded instrument's view, for rounding onto its tick.
            underlying_price (decimal.Decimal): The underlying's last traded price.
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when it cannot be rounded.
        """
        start_price = decimal.Decimal(self.parent.parameters['start_price'])
        underlying_start = decimal.Decimal(
            self.parent.parameters['underlying_start'],
        )
        delta = self.number('delta', True)
        price = start_price + delta * (underlying_price - underlying_start)
        lowest, highest = self.read_range()
        if lowest is not None and price < lowest:
            price = lowest
        if highest is not None and price > highest:
            price = highest
        tick_size = self.tick_size()
        if tick_size and price < tick_size:
            price = tick_size
        return view.rounded(price, transaction_type)

    def run(self, intent, started_at):
        """Places the order at the caller's price and remembers where the underlying stood.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a missing underlying or delta, a bad range or step, or an order that is not a LIMIT with a price, and 503 when the underlying's quote has no last price.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        underlying = self.underlying()
        self.number('delta', True)
        self.read_range()
        self.read_step_ticks()
        if order.order_type != 'LIMIT' or order.price is None:
            raise RefusedRequestError.refusal(
                'an underlying peg starts from the price you give, so it must '
                'be a LIMIT order with a price',
                400,
            )

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(underlying, True, False)
        underlying_start = self.underlying_price({underlying: quote})
        if underlying_start is None:
            raise RefusedRequestError.refusal(
                'an underlying peg measures the underlying\'s moves from now, '
                'and its quote does not carry a last traded price yet',
                503,
                instrument_id=underlying,
            )
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['start_price'] = str(order.price)
        self.parent.parameters['underlying_start'] = str(underlying_start)
        self.record_received()
        self.save()
        body, status, _ = self.place_leg('entry', order, started_at)
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        body['underlying_start'] = str(underlying_start)
        return body, status

    def on_price_tick(self, quotes, now):
        """Moves the resting order by delta times the underlying's move, once the move is at least a step.

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
        view = self.view(quotes)
        price = self.target_price(view, underlying_price, leg.transaction_type)
        if price is None:
            return False
        current = decimal.Decimal(str(leg.price))
        if abs(price - current) < tick_size * self.read_step_ticks():
            return False
        moved = self.reprice_leg(
            leg,
            price,
            None,
            f'the underlying is at {underlying_price}, so the peg moved to '
            f'{price}',
        )
        if moved:
            self.save()
        return moved

    def on_leg_modified(self, leg, before):
        """Re-anchors the peg at the caller's new price and the underlying's price now.

        Args:
            leg (OrderLeg): The pegged leg, holding its new price.
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
                f'underlying to re-anchor its peg: {refusal.body.get("error")}'
            )
            return
        underlying_price = self.underlying_price({underlying: quote})
        if underlying_price is None:
            return
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['start_price'] = str(leg.price)
        self.parent.parameters['underlying_start'] = str(underlying_price)
        self.record_parameters(
            f'the caller moved the price to {leg.price}, so the peg follows '
            f'the underlying from {underlying_price}'
        )
        self.save()
