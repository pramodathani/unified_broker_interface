"""A stop that closes a position and opens the same size the other way."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.close_on_trigger import (
    CloseOnTrigger,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)

METHODS = (
    'sequential',
    'double',
)


class StopAndReverse(CloseOnTrigger):
    """Waits for a price, then flips the position: a long of 75 becomes a short of 75 (the Atlas's G13).

    It first cancels every order resting on the instrument, as `close_on_trigger` does, which frees the margin the new side will need. Then `method` decides how the flip is sent:

    - `sequential`, the default, sends a closing order for the position and, once that has completely filled, a second order of the same size and side that opens the reverse. Nothing opens until the old position is gone, at the cost of a gap between the two.
    - `double` sends one order for twice the position. It is faster, but the exchange sees one order for double the size, and the broker must accept the margin for the new side before the old one has closed.

    Like `close_on_trigger`, it acts on the net position held when it fires, and `transaction_type` is the side that opened it.
    """

    SYNTHETIC_TYPE = 'stop_and_reverse'
    ARMED_MESSAGE = 'the level is reached, and then the position is closed and reversed'

    def read_method(self):
        """How the flip is sent.

        Returns:
            str: One of `METHODS`.

        Raises:
            RefusedRequestError: With HTTP 400 for another value.
        """
        method = self.parent.parameters.get('method') or 'sequential'
        if method not in METHODS:
            raise RefusedRequestError.refusal(
                f'method must be one of {", ".join(METHODS)}, not {method!r}',
                400,
            )
        return method

    def run(self, intent, started_at):
        """Records the order, refusing early when the method or the product cannot be read.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the method, the product or the trigger cannot be read.
        """
        self.read_method()
        return super().run(intent, started_at)

    def fire(self, child, price, level):
        """Cancels what rests on the instrument, then sends the close, or the doubled order.

        Args:
            child (PlaceOrderRequest): The caller's order.
            price (decimal.Decimal): The price that reached the level.
            level (decimal.Decimal): The level.

        Returns:
            bool: True, because the trigger fired whatever happened next.
        """
        closer = PositionCloser(self)
        instrument_ids = {
            self.parent.instrument_id,
        }
        cancelled = closer.cancel_resting(
            instrument_ids,
            'cancelled before reversing the position, to free its margin',
        )
        positions = closer.open_positions(
            self.position_product(child),
            instrument_ids,
        )
        if not positions:
            self.record_state(
                'completed',
                f'{price} reached the trigger at {level}; nothing was held to '
                'reverse',
            )
            self.save()
            return True
        instrument_id, quantity = positions[0]
        method = self.read_method()
        if method == 'double':
            role = 'reverse'
            order = closer.closing_order(instrument_id, quantity * 2)
        else:
            role = 'close'
            order = closer.closing_order(instrument_id, quantity)
        if order is None:
            self.record_state(
                'failed',
                f'{price} reached the trigger at {level}, but the book gave '
                'no price to trade at',
            )
            self.save()
            return True
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['reverse_from'] = str(quantity)
        self.save()
        body, _, _ = self.place_leg(role, order, None, self.chosen_broker())
        outcome = body.get('outcome')
        self.record_state(
            self.state_after_firing(outcome),
            f'{price} reached the trigger at {level}; {cancelled} resting '
            f'orders cancelled, then the {role} order was '
            f'{body.get("status_message") or outcome}',
        )
        self.save()
        return True

    def on_leg_update(self, leg, changes):
        """Sends the reverse once a sequential close has completely filled.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'close' or leg.state != 'filled':
            return
        for other in self.parent.legs:
            if other.role == 'reverse':
                return
        quantity = self.parent.parameters.get('reverse_from')
        if quantity is None:
            return
        closer = PositionCloser(self)
        order = closer.closing_order(
            self.parent.instrument_id,
            decimal.Decimal(str(quantity)),
        )
        if order is None:
            self.record_state(
                'failed',
                'the position closed, but the book gave no price to reverse at',
            )
            self.save()
            return
        body, _, _ = self.place_leg('reverse', order, None, leg.broker)
        self.record_state(
            self.state_after_firing(body.get('outcome')),
            f'the close filled, so the reverse was '
            f'{body.get("status_message") or body.get("outcome")}',
        )
        self.save()

