"""A visible limit at one price, willing to pay a little more without showing it."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

DEFAULT_BUFFER_TICKS = 2


class Discretionary(SyntheticOrder):
    """An order that shows one price and will quietly accept a worse one within a stated distance.

    The visible limit rests where the caller said, and does what any limit does. The discretion is the part nobody else can see: if the other side comes within `discretion_points` of that price, the engine takes it, without ever having advertised that it would.

    The reason to want this is that a limit order is information. A large bid resting at 1000 tells everybody watching the book that somebody wants 1000, and in a thin option book that is enough for the offer to sit at 1000.50 all day waiting for the bid to come up. A discretionary order bids 1000 and takes 1000.25 when it appears, and the book never learns that 1000.25 was acceptable.

    `discretion_quantity` is how much is taken when the chance comes, and it defaults to the whole of what is still resting, which is the usual intent: the order was going to trade at 1000 anyway, so trading at 1000.25 now is simply better than waiting. Setting it smaller takes a slice and leaves the rest showing at the original price.

    **The resting order is reduced before the taking order is sent.** Both of them can fill, and in a fast market both of them will if they are allowed to overlap. Reducing first makes the window as small as one request rather than as large as the time between two, which is the same rule every linked type in this package follows and the same bug the Atlas calls the recurring one.
    """

    SYNTHETIC_TYPE = 'discretionary'
    WANTS_PRICES = True

    def read_discretion(self):
        """How far past the visible price this order will quietly go.

        Returns:
            decimal.Decimal: The distance, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not above zero.
        """
        value = self.parent.parameters.get('discretion_points')
        if value is None:
            raise RefusedRequestError.refusal(
                'a discretionary order needs discretion_points to say how far '
                'past its visible price it will go',
                400,
            )
        try:
            points = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'discretion_points must be a number, not {value!r}',
                400,
            )
        if not points.is_finite() or points <= 0:
            raise RefusedRequestError.refusal(
                f'discretion_points must be above zero, not {points}',
                400,
            )
        return points

    def read_discretion_quantity(self, resting):
        """How much is taken when the chance comes.

        Args:
            resting (int): How much of the visible order is still open.

        Returns:
            int: The quantity to take, never more than is resting.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number above zero.
        """
        value = self.parent.parameters.get('discretion_quantity')
        if value is None:
            return resting
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'discretion_quantity must be a whole number, not {value!r}',
                400,
            )
        if quantity < 1:
            raise RefusedRequestError.refusal(
                f'discretion_quantity must be at least one, not {quantity}',
                400,
            )
        return min(quantity, resting)

    def run(self, intent, started_at):
        """Places the visible limit where the caller asked, and starts watching for the chance.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad discretion, and 503 when the instrument has no agreed tick size.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.read_discretion()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
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
        return body, status

    def reachable_price(self, leg):
        """The worst price this order will quietly accept.

        Args:
            leg (OrderLeg): The visible order.

        Returns:
            decimal.Decimal: The limit of the discretion.
        """
        visible = decimal.Decimal(str(leg.price))
        points = self.read_discretion()
        if leg.transaction_type == 'BUY':
            return visible + points
        return visible - points

    def on_price_tick(self, quotes, now):
        """Takes the other side when it comes within the discretion.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a taking order was sent.
        """
        leg = self.resting_leg()
        if leg is None or leg.price is None:
            return False
        view = self.view(quotes)
        touch = view.opposite_touch(leg.transaction_type)
        if touch is None:
            return False
        reachable = self.reachable_price(leg)
        if leg.transaction_type == 'BUY':
            within = touch <= reachable
        else:
            within = touch >= reachable
        if not within:
            return False

        resting = (leg.quantity or 0) - (leg.filled_quantity or 0)
        if resting < 1:
            return False
        taking = self.read_discretion_quantity(resting)
        if not self.make_room(leg, resting, taking, touch):
            return False
        return self.take(leg, taking, touch, view)

    def make_room(self, leg, resting, taking, touch):
        """Takes the quantity about to be taken out of the visible order, so both cannot fill.

        Args:
            leg (OrderLeg): The visible order.
            resting (int): How much of it is still open.
            taking (int): How much is about to be taken.
            touch (decimal.Decimal): The price that came within reach, for the message.

        Returns:
            bool: True when the visible order is out of the way.
        """
        reason = (
            f'the other side reached {touch}, which is inside the discretion, '
            f'so {taking} is being taken'
        )
        if taking >= resting:
            return self.cancel_leg(leg, reason)
        return self.reduce_leg(leg, resting - taking, reason)

    def within_discretion(self, price, leg):
        """The price, held back to the furthest the caller said they would go.

        The taking order is priced a couple of ticks past the touch, so that it clears whatever is sitting there rather than joining it. Two ticks past a touch that is itself right at the edge of the discretion is two ticks past what the caller agreed to, which would quietly spend money they did not offer.

        Args:
            price (decimal.Decimal): The price the buffer works out to.
            leg (OrderLeg): The visible order.

        Returns:
            decimal.Decimal: The price, or the edge of the discretion.
        """
        reachable = self.reachable_price(leg)
        if leg.transaction_type == 'BUY':
            return min(price, reachable)
        return max(price, reachable)

    def take(self, leg, taking, touch, view):
        """Sends the order that takes what came within reach.

        Args:
            leg (OrderLeg): The visible order.
            taking (int): How much to take.
            touch (decimal.Decimal): The price on the other side.
            view (MarketView): The live quote.

        Returns:
            bool: True when the taking order was sent.
        """
        price = view.moved(
            touch,
            DEFAULT_BUFFER_TICKS,
            leg.transaction_type,
            True,
        )
        price = view.rounded(price, leg.transaction_type)
        if price is None or price <= 0:
            return False
        price = self.within_discretion(price, leg)
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = taking
        body['transaction_type'] = leg.transaction_type
        body['price'] = str(price)
        self.place_leg(
            'discretion',
            self.read_order(body),
            None,
            self.chosen_broker(),
        )
        self.save()
        return True

    def resting_leg(self):
        """The visible order, while it can still fill.

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
