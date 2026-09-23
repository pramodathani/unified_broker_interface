"""A large order that only ever shows a little of itself."""

import zlib

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder


class Iceberg(SyntheticOrder):
    """An order that rests one slice at a time and places the next when that slice fills.

    Somebody who wants to buy ten thousand and shows a bid for ten thousand has told the market exactly that, and the market prices accordingly. Showing five hundred at a time and replacing it as it fills gets the same job done while looking, from outside, like ordinary two-way trading.

    NSE has this natively in the cash segment as disclosed quantity, and where it is available it is better in one important way: the exchange keeps the order's original time priority across every replenishment, so the hidden part never loses its place in the queue. This version cannot do that. Each new slice is a new order and joins the back of its price level's queue, which is the real cost of building it rather than using the exchange's own.

    `slice_quantity` is what shows. `randomise_percent` varies it by up to that much either way, which matters more than it sounds: a bid that is replaced at exactly five hundred every time, five times in a row, is as informative as showing ten thousand once. Somebody watching the book can see the pattern and knows there is more behind it.

    The replenishment is driven by fills rather than by the clock, which is what makes this different from a time-weighted order: nothing goes out until the market has actually taken what was showing.
    """

    SYNTHETIC_TYPE = 'iceberg'

    def read_slice_quantity(self, order):
        """How much of the order shows at a time.

        Returns:
            int: The visible size.

        Args:
            order (PlaceOrderRequest): The validated order.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing, not a whole number above zero, or not smaller than the order itself.
        """
        value = self.parent.parameters.get('slice_quantity')
        if value is None:
            raise RefusedRequestError.refusal(
                'an iceberg needs slice_quantity, how much of it shows at a '
                'time',
                400,
            )
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'slice_quantity must be a whole number, not {value!r}',
                400,
            )
        if quantity < 1:
            raise RefusedRequestError.refusal(
                f'slice_quantity must be at least one, not {quantity}',
                400,
            )
        if quantity >= order.quantity:
            raise RefusedRequestError.refusal(
                f'slice_quantity of {quantity} is not smaller than the order '
                f'of {order.quantity}, so nothing would be hidden',
                400,
            )
        return quantity

    def read_randomise_percent(self):
        """How much the visible size varies from one slice to the next.

        Returns:
            float: The percentage, at or above zero and below one hundred.

        Raises:
            RefusedRequestError: With HTTP 400 when it is out of range.
        """
        value = self.parent.parameters.get('randomise_percent', 0)
        try:
            percent = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'randomise_percent must be a number, not {value!r}',
                400,
            )
        if percent < 0 or percent >= 100:
            raise RefusedRequestError.refusal(
                f'randomise_percent must be at or above zero and below 100, '
                f'not {percent}',
                400,
            )
        return percent

    def next_size(self, order):
        """How big the next visible slice is, never more than is left to do.

        The randomisation is deterministic for a given parent and slice number rather than drawn from a random source. A recorded scenario has to give the same answer every time it runs, and a pattern derived from a parent's own identifier is as unguessable from outside the account as a random one while staying reproducible inside it.

        It uses a checksum rather than Python's own `hash`, because `hash` of a string is salted differently in every process, so the same parent would get different slice sizes after a restart and no recording of it could ever match.

        Args:
            order (PlaceOrderRequest): The validated order.

        Returns:
            int: The quantity for the next slice, or zero when the order is done.
        """
        placed = self.parent.parameters.get('placed_quantity') or 0
        remaining = order.quantity - placed
        if remaining < 1:
            return 0
        wanted = self.read_slice_quantity(order)
        percent = self.read_randomise_percent()
        if percent > 0:
            seed = zlib.crc32(
                f'{self.parent.parent_order_id}:{len(self.parent.legs)}'.encode()
            )
            spread = wanted * percent / 100
            offset = (seed % 2001) / 1000 - 1
            wanted = int(round(wanted + spread * offset))
            wanted = max(wanted, 1)
        return min(wanted, remaining)

    def run(self, intent, started_at):
        """Shows the first slice.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.read_slice_quantity(order)
        self.read_randomise_percent()

        if order.dry_run:
            prepared = self.placement.prepare(
                order.with_quantities(self.read_slice_quantity(order), 0),
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['placed_quantity'] = 0
        self.save()

        quantity = self.next_size(order)
        body, status, _ = self.place_leg(
            'slice',
            order.with_quantities(quantity, 0),
            started_at,
        )
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['placed_quantity'] = quantity
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        body['hidden_quantity'] = order.quantity - quantity
        return body, status

    def on_leg_update(self, leg, changes):
        """Shows the next slice once the one on display has been taken.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'slice' or not leg.is_finished():
            return
        if leg.state != 'filled':
            return
        order = self.concrete_order(self.read_order(self.parent.body))
        quantity = self.next_size(order)
        if quantity < 1:
            if not self.parent.is_terminal():
                self.record_state('completed', 'every slice has been filled')
                self.save()
            return
        placed = self.parent.parameters.get('placed_quantity') or 0
        self.place_leg(
            'slice',
            order.with_quantities(quantity, 0),
            None,
            self.chosen_broker(),
        )
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['placed_quantity'] = placed + quantity
        self.save()
