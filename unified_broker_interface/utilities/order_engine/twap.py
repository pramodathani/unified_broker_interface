"""A large order spread evenly over time, so it is not all paid for at one moment's price."""

import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

MOST_SLICES = 60


class Twap(SyntheticOrder):
    """Splits an order into `slices` sent at even intervals over `over_minutes`.

    Time-weighted average price: an order large enough to move the book against itself is spread over an hour so that what it pays is closer to the hour's average than to the price at the moment somebody pressed the button.

    It is the freeze slicer's opposite in intent. The slicer splits an order because an exchange will not take it whole; this splits one that an exchange would take whole, because taking it whole would cost more than waiting.

    The first slice goes immediately and the rest on the clock, so a caller sees an order id back rather than a promise. A slice that is due while the engine was busy is sent as soon as it is noticed rather than skipped, which means a slow minute shortens the gap to the next slice rather than dropping one.

    Every slice goes to the broker the first one chose, as every multi-leg type does: a position spread across brokers takes one order per broker to close.

    Nothing here watches the price. A slice is sent because its time has come, which is what makes it a TWAP rather than one of the types that chase.
    """

    SYNTHETIC_TYPE = 'twap'
    WANTS_CLOCK = True

    def run(self, intent, started_at):
        """Records the schedule and sends the first slice.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        slices, over_minutes = self.schedule(order)

        if order.dry_run:
            prepared = self.placement.prepare(
                self.slice_order(order, slices, 0),
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['slice_count'] = slices
        self.parent.parameters['interval_seconds'] = (
            over_minutes * 60 / slices
        )
        # The same clock the tick reads, so a slice is due when the tick says it is. Taking this
        # from anywhere else would make the schedule depend on two clocks agreeing.
        self.parent.parameters['started_at'] = time.time()
        self.record_received()
        self.save()

        body, status, _ = self.place_leg(
            'slice',
            self.slice_order(order, slices, 0),
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
        body['slices'] = slices
        return body, status

    def schedule(self, order):
        """How many slices, over how long.

        Args:
            order (PlaceOrderRequest): The validated order.

        Returns:
            tuple: The number of slices (int) and the minutes to spread them over (float).

        Raises:
            RefusedRequestError: With HTTP 400 when either setting is missing or unusable.
        """
        parameters = self.parent.parameters
        try:
            slices = int(parameters.get('slices'))
        except (TypeError, ValueError):
            slices = None
        try:
            over_minutes = float(parameters.get('over_minutes'))
        except (TypeError, ValueError):
            over_minutes = None
        if slices is None or slices < 2 or slices > MOST_SLICES:
            raise RefusedRequestError.refusal(
                f'a twap needs slices between 2 and {MOST_SLICES}',
                400,
            )
        if over_minutes is None or over_minutes <= 0:
            raise RefusedRequestError.refusal(
                'a twap needs over_minutes above zero, the time to spread the '
                'order across',
                400,
            )
        if order.quantity < slices:
            raise RefusedRequestError.refusal(
                f'a twap of {slices} slices needs a quantity of at least '
                f'{slices}, not {order.quantity}',
                400,
            )
        return slices, over_minutes

    def slice_order(self, order, slices, index):
        """The order for one slice, sharing the quantity as evenly as whole units allow.

        Args:
            order (PlaceOrderRequest): The validated order.
            slices (int): How many slices there are.
            index (int): Which slice this is, counting from zero.

        Returns:
            PlaceOrderRequest: The slice.
        """
        each = order.quantity // slices
        remainder = order.quantity - each * slices
        quantity = each + (1 if index < remainder else 0)
        return order.with_quantities(quantity, 0)

    def on_clock_tick(self, now):
        """Sends any slice whose time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a slice was sent on this tick.
        """
        parameters = self.parent.parameters
        slices = parameters.get('slice_count')
        interval = parameters.get('interval_seconds')
        started_at = parameters.get('started_at')
        if not isinstance(slices, int) or not isinstance(
            interval,
            (int, float),
        ):
            return False
        if not isinstance(started_at, (int, float)):
            return False

        sent = len(self.parent.legs)
        if sent >= slices:
            return False
        if now < started_at + interval * sent:
            return False

        order = self.concrete_order(self.read_order(self.parent.body))
        first = self.parent.legs[0] if self.parent.legs else None
        body, _, _ = self.place_leg(
            'slice',
            self.slice_order(order, slices, sent),
            None,
            first.broker if first else None,
        )
        if sent + 1 >= slices:
            outcome = body.get('outcome')
            self.record_state(
                'working' if outcome == 'accepted' else 'failed',
                'every slice has been sent',
            )
        self.save()
        return True
