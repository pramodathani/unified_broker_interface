"""A resting limit order whose price follows a reference in the book."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

REFERENCES = (
    'own_touch',
    'mid',
    'opposite_touch',
)


class Peg(SyntheticOrder):
    """A limit order that is re-priced to stay at a named place in the book.

    Three pegs, and they differ only in what they follow. **Peg to primary** (`own_touch`) joins the best price on your own side, so a buy sits on the bid: it never takes liquidity and it is always first in line to be joined. **Peg to midpoint** (`mid`) sits between the touch, which fills against anybody willing to meet in the middle. **Peg to market** (`opposite_touch`) sits on the other side's touch, so a buy sits on the offer and fills at once; it is used to stay filled rather than to rest.

    `offset_ticks` moves the order away from filling, so a buy pegged to the bid with an offset of two ticks sits two ticks below it. A negative offset moves the other way, towards the market.

    `cap_price` is the price it will never go past: the most a buy will bid, the least a sell will offer. An order whose reference moves past the cap stays at the cap rather than following, because the cap is what the caller said the trade is worth and the reference is only where the crowd is.

    **The cost of every move is a place in the queue.** An exchange orders resting orders at one price by the time they arrived, so a change to the price sends the order to the back of its new price's queue. A peg that follows every flicker of the bid is therefore not just expensive in requests, it is worse at getting filled than one that sits still. That is why the re-pricing throttle and the refusal to send a move that changes nothing both sit in `reprice_leg` rather than here: they are the difference between a peg that works and one that churns.
    """

    SYNTHETIC_TYPE = 'peg'
    WANTS_PRICES = True

    def run(self, intent, started_at):
        """Places the order where the reference is now, and starts following it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for an unknown reference, and 503 when there is no tick size or no quote to place against.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        reference = self.reference()
        self.read_offset()
        self.read_cap()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        price = self.wanted_price(
            self.view({self.parent.instrument_id: quote}),
            order.transaction_type,
        )
        if price is None:
            raise RefusedRequestError.refusal(
                f'a peg to {reference} needs that price in the live quote and '
                'the quote does not carry it yet',
                503,
                instrument_id=self.parent.instrument_id,
            )

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
        return body, status

    def reference(self):
        """Which price in the book this peg follows.

        Returns:
            str: One of `REFERENCES`.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller named something else.
        """
        reference = self.parent.parameters.get('reference', 'own_touch')
        if reference not in REFERENCES:
            raise RefusedRequestError.refusal(
                f'reference must be one of {", ".join(REFERENCES)}, not '
                f'{reference!r}',
                400,
            )
        return reference

    def read_offset(self):
        """How many ticks away from the reference the order sits.

        Returns:
            int: The offset, positive away from the market.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number.
        """
        value = self.parent.parameters.get('offset_ticks', 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'offset_ticks must be a whole number of ticks, not {value!r}',
                400,
            )

    def read_cap(self):
        """The price this peg will not go past.

        Returns:
            decimal.Decimal | None: The cap, or None when the caller set none.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a price.
        """
        value = self.parent.parameters.get('cap_price')
        if value is None:
            return None
        try:
            cap = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'cap_price must be a price, not {value!r}',
                400,
            )
        if cap <= 0:
            raise RefusedRequestError.refusal(
                f'cap_price must be above zero, not {cap}',
                400,
            )
        return cap

    def wanted_price(self, view, transaction_type):
        """Where this peg's order should be, given the book as it is now.

        Args:
            view (MarketView): The live quote.
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when the book does not carry the reference yet.
        """
        reference = self.parent.parameters.get('reference', 'own_touch')
        if reference == 'mid':
            price = view.mid()
        elif reference == 'opposite_touch':
            price = view.opposite_touch(transaction_type)
        else:
            price = view.own_touch(transaction_type)
        if price is None:
            return None
        offset = self.read_offset()
        if offset:
            price = view.moved(price, offset, transaction_type, False)
        price = view.rounded(price, transaction_type)
        if price is None:
            return None
        return self.capped(price, transaction_type)

    def capped(self, price, transaction_type):
        """The price, held back to the cap when it has gone past it.

        Args:
            price (decimal.Decimal): The price the reference works out to.
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal: The price, or the cap.
        """
        cap = self.read_cap()
        if cap is None:
            return price
        if transaction_type == 'BUY':
            return min(price, cap)
        return max(price, cap)

    def priced(self, order, price):
        """The order, with a price worked out from the book rather than from the caller.

        Args:
            order (PlaceOrderRequest): The order as the caller sent it.
            price (decimal.Decimal): The price to send.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = order.transaction_type
        body['price'] = str(price)
        return self.read_order(body)

    def on_price_tick(self, quotes, now):
        """Moves the resting order to wherever its reference is now.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was moved.
        """
        leg = self.working_leg()
        if leg is None:
            return False
        view = self.view(quotes)
        if not view.is_readable():
            return False
        price = self.wanted_price(view, leg.transaction_type)
        if price is None:
            return False
        moved = self.reprice_leg(
            leg,
            price,
            None,
            f'the {self.parent.parameters.get("reference", "own_touch")} peg '
            f'moved to {price}',
        )
        if moved:
            self.save()
        return moved

    def working_leg(self):
        """The one leg this peg is following the market with, while it can still fill.

        Returns:
            OrderLeg | None: The leg, or None when there is nothing resting.
        """
        for leg in self.parent.legs:
            if leg.role != 'entry' or leg.is_finished():
                continue
            if leg.broker_order_id is None:
                continue
            return leg
        return None
