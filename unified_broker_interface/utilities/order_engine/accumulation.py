"""Buying a fixed amount on a schedule, patiently, for as long as the schedule runs."""

import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

MOST_PURCHASES = 100


class Accumulation(SyntheticOrder):
    """A fixed quantity bought every `every_minutes`, `purchases` times, each one resting patiently.

    This is the systematic investment plan, expressed as an order. The idea is the oldest one in investing and the arithmetic behind it is genuinely in the buyer's favour: a fixed amount buys more units when the price is low and fewer when it is high, so the average paid is below the average price over the period.

    It looks like a time-weighted average price order and the intent is different, which is worth saying because it decides how each purchase is priced. A time-weighted order is working a decision already made and cares mostly about finishing; it gets more aggressive as its window runs out. This has no window and no obligation to finish anything, so **each purchase rests on its own side of the book** — a buy joins the bid — and simply does not fill if nobody meets it. Paying the spread on every purchase, several hundred times over a year, is a real cost against a strategy whose whole edge is patience.

    The consequence is that a purchase can go unfilled, and this does not chase it. The order rests until the day ends and the next purchase is a new order at the new price. Somebody who would rather be certain of accumulating wants a chaser or a plain marketable order on a schedule instead.

    The schedule is measured from when the order was placed rather than from a clock time, so "every thirty minutes, eight times" means what it says whenever it was started.
    """

    SYNTHETIC_TYPE = 'accumulation'
    WANTS_CLOCK = True

    def read_every_minutes(self):
        """How long between purchases.

        Returns:
            float: The gap in minutes.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not above zero.
        """
        value = self.parent.parameters.get('every_minutes')
        if value is None:
            raise RefusedRequestError.refusal(
                'an accumulation needs every_minutes, how long to wait between '
                'purchases',
                400,
            )
        try:
            minutes = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'every_minutes must be a number of minutes, not {value!r}',
                400,
            )
        if minutes <= 0:
            raise RefusedRequestError.refusal(
                f'every_minutes must be above zero, not {minutes}',
                400,
            )
        return minutes

    def read_purchases(self):
        """How many purchases the schedule makes.

        Returns:
            int: The count.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or out of range.
        """
        value = self.parent.parameters.get('purchases')
        if value is None:
            raise RefusedRequestError.refusal(
                'an accumulation needs purchases, how many times to buy',
                400,
            )
        try:
            purchases = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'purchases must be a whole number, not {value!r}',
                400,
            )
        if purchases < 1 or purchases > MOST_PURCHASES:
            raise RefusedRequestError.refusal(
                f'purchases must be between 1 and {MOST_PURCHASES}, not '
                f'{purchases}',
                400,
            )
        return purchases

    def run(self, intent, started_at):
        """Makes the first purchase and sets the schedule for the rest.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad schedule, and 503 when there is no tick size or no quote to rest against.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        every_minutes = self.read_every_minutes()
        purchases = self.read_purchases()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['interval_seconds'] = every_minutes * 60
        # The same clock the tick reads, so a purchase is due when the tick says it is.
        self.parent.parameters['started_at'] = time.time()
        self.save()

        body, status, _ = self.buy_once(order, started_at)
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        body['purchases'] = purchases
        return body, status

    def buy_once(self, order, started_at):
        """One purchase, resting on its own side of the book.

        Args:
            order (PlaceOrderRequest): The validated order.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None for a purchase made on the clock.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: With HTTP 503 when the live quote does not carry this order's own side of the book.
        """
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        view = self.view({self.parent.instrument_id: quote})
        price = view.own_touch(order.transaction_type)
        if price is None:
            raise RefusedRequestError.refusal(
                'an accumulation rests on its own side of the book and the '
                'live quote does not carry that side yet',
                503,
                instrument_id=self.parent.instrument_id,
            )
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = order.transaction_type
        body['price'] = str(price)
        return self.place_leg(
            'purchase',
            self.read_order(body),
            started_at,
            self.chosen_broker(),
        )

    def on_clock_tick(self, now):
        """Makes the next purchase when its time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a purchase was made on this tick.
        """
        interval = self.parent.parameters.get('interval_seconds')
        started_at = self.parent.parameters.get('started_at')
        if not isinstance(interval, (int, float)):
            return False
        if not isinstance(started_at, (int, float)):
            return False
        made = len(self.parent.legs)
        purchases = self.read_purchases()
        if made >= purchases:
            return False
        if now < started_at + interval * made:
            return False
        order = self.concrete_order(self.read_order(self.parent.body))
        try:
            self.buy_once(order, None)
        except RefusedRequestError as refusal:
            self.logger.warning(
                f'Accumulation {self.parent.parent_order_id} could not buy: '
                f'{refusal.body.get("error")}'
            )
            return False
        if made + 1 >= purchases:
            self.record_state('working', 'every purchase has been made')
        self.save()
        return True
