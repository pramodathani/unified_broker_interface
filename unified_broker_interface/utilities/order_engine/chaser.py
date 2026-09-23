"""A limit order that starts passive and walks towards the market until it fills."""

import decimal
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

DEFAULT_STEP_TICKS = 1
DEFAULT_STEP_SECONDS = 5.0


class Chaser(SyntheticOrder):
    """A limit that joins its own side of the book and steps towards the other until it trades.

    This is the practical way to get out of an option position without paying the spread every time, and it is the type the Atlas leans on most: several other recipes end with "exit with a chaser" rather than with a market order, because market orders are no longer what they were in India.

    It works the way a patient seller in a market does. Start by asking a fair price and wait. If nobody comes, lower it a little. Wait again, lower again. At some point either somebody takes it or you have reached the least you will accept, and then you decide whether to meet the buyer at their price or go home.

    Three numbers say how impatient it is. `step_ticks` is how far it moves each time, `step_seconds` is how long it waits between moves, and `cap_price` is the worst price it will take: the most a buy will pay, the least a sell will accept. Reaching the cap is not the end — the order simply rests there, which is exactly what a limit at the cap should do.

    `cross_after_seconds` is the ending. When it is set and that long has gone by with the order still open, the order is moved to the other side's touch, which fills it immediately against whatever is resting there. Without it, the chaser walks to its cap and waits there for the rest of the day.

    Every step costs a place in the queue, because an exchange orders a price level by arrival time and a change to the price rejoins at the back. Stepping slowly is therefore not only cheaper in requests, it is often better at filling, and `step_seconds` rather than every tick is the reason this is a chaser and not a peg.
    """

    SYNTHETIC_TYPE = 'chaser'
    WANTS_PRICES = True

    def run(self, intent, started_at):
        """Places the order on its own side of the book and starts walking it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad step or cap, and 503 when there is no tick size or no quote to start from.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.read_step_ticks()
        self.read_step_seconds()
        cap = self.read_cap()

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
        view = self.view({self.parent.instrument_id: quote})
        price = view.own_touch(order.transaction_type)
        if price is None:
            raise RefusedRequestError.refusal(
                'a chaser starts on its own side of the book and the live '
                'quote does not carry that side yet',
                503,
                instrument_id=self.parent.instrument_id,
            )
        if cap is not None:
            price = self.capped(price, order.transaction_type, cap)

        self.record_received()
        self.parent.parameters['stepped_at'] = self.unix_now()
        self.parent.parameters['started_walking_at'] = self.unix_now()
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

    def unix_now(self):
        """The Unix time, read from the same clock a price tick reads.

        A schedule and the thing that checks it have to read one clock. Recording the start from one and comparing it against another makes the first step either immediate or an hour away, depending on which way the two clocks happen to differ.

        Returns:
            float: The Unix time.
        """
        return time.time()

    def read_step_ticks(self):
        """How many ticks the order moves each time it steps.

        Returns:
            int: The step, at least one tick.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number above zero.
        """
        value = self.parent.parameters.get('step_ticks', DEFAULT_STEP_TICKS)
        try:
            ticks = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'step_ticks must be a whole number of ticks, not {value!r}',
                400,
            )
        if ticks < 1:
            raise RefusedRequestError.refusal(
                f'step_ticks must be at least one tick, not {ticks}',
                400,
            )
        return ticks

    def read_step_seconds(self):
        """How long the order waits between steps.

        Returns:
            float: The wait in seconds.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number above zero.
        """
        value = self.parent.parameters.get(
            'step_seconds',
            DEFAULT_STEP_SECONDS,
        )
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'step_seconds must be a number of seconds, not {value!r}',
                400,
            )
        if seconds <= 0:
            raise RefusedRequestError.refusal(
                f'step_seconds must be above zero, not {seconds}',
                400,
            )
        return seconds

    def read_cap(self):
        """The worst price this chaser will take.

        Returns:
            decimal.Decimal | None: The cap, or None when the caller set none.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a price above zero.
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

    def read_cross_after(self):
        """How long the chaser walks before it gives up and crosses the spread.

        Returns:
            float | None: The seconds, or None when it never crosses.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number above zero.
        """
        value = self.parent.parameters.get('cross_after_seconds')
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                'cross_after_seconds must be a number of seconds, not '
                f'{value!r}',
                400,
            )
        if seconds <= 0:
            raise RefusedRequestError.refusal(
                f'cross_after_seconds must be above zero, not {seconds}',
                400,
            )
        return seconds

    def capped(self, price, transaction_type, cap):
        """The price, held back to the cap when it has gone past it.

        Args:
            price (decimal.Decimal): The price the step works out to.
            transaction_type (str): BUY or SELL.
            cap (decimal.Decimal): The worst price allowed.

        Returns:
            decimal.Decimal: The price, or the cap.
        """
        if transaction_type == 'BUY':
            return min(price, cap)
        return max(price, cap)

    def priced(self, order, price):
        """The order, at a price the chaser worked out rather than one the caller sent.

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
        """Takes one step towards the market, or crosses the spread when the time is up.

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
        if self.should_cross(now):
            return self.cross(leg, view)
        stepped_at = self.parent.parameters.get('stepped_at')
        if not isinstance(stepped_at, (int, float)):
            stepped_at = 0
        if (now - stepped_at) < self.read_step_seconds():
            return False
        return self.step(leg, view, now)

    def should_cross(self, now):
        """Whether the chaser has walked for as long as it was given.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when it should cross the spread now.
        """
        cross_after = self.read_cross_after()
        if cross_after is None:
            return False
        started = self.parent.parameters.get('started_walking_at')
        if not isinstance(started, (int, float)):
            return False
        return (now - started) >= cross_after

    def cross(self, leg, view):
        """Moves the order to the other side's touch, where it fills against what is resting.

        Args:
            leg (OrderLeg): The resting order.
            view (MarketView): The live quote.

        Returns:
            bool: True when the order was moved.
        """
        price = view.opposite_touch(leg.transaction_type)
        if price is None:
            return False
        cap = self.read_cap()
        if cap is not None:
            price = self.capped(price, leg.transaction_type, cap)
        moved = self.reprice_leg(
            leg,
            price,
            None,
            f'the chaser ran out of time and crossed to {price}',
        )
        if moved:
            self.save()
        return moved

    def step(self, leg, view, now):
        """Moves the order one step closer to the market.

        The step is taken from where the order actually is rather than from where the book is, so a chaser walks steadily even while the market moves around it, and cannot be dragged backwards by a bid that ticked away.

        Args:
            leg (OrderLeg): The resting order.
            view (MarketView): The live quote.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was moved.
        """
        if leg.price is None:
            return False
        here = view.rounded(
            decimal.Decimal(str(leg.price)),
            leg.transaction_type,
        )
        if here is None:
            return False
        price = view.moved(
            here,
            self.read_step_ticks(),
            leg.transaction_type,
            True,
        )
        cap = self.read_cap()
        if cap is not None:
            price = self.capped(price, leg.transaction_type, cap)
        touch = view.opposite_touch(leg.transaction_type)
        if touch is not None:
            price = self.capped(price, leg.transaction_type, touch)
        moved = self.reprice_leg(
            leg,
            price,
            None,
            f'the chaser stepped to {price}',
        )
        if moved:
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['stepped_at'] = now
            self.save()
        return moved

    def working_leg(self):
        """The one order the chaser is walking, while it can still fill.

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
