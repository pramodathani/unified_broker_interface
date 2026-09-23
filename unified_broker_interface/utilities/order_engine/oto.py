"""One order that places another once it fills."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder


class OneTriggersOther(SyntheticOrder):
    """An order that, when it fills, places a second one the caller described in advance.

    The plainest of the linked types and the one the others are built from: a bracket is this with two children that also watch each other.

    The child is sized to what the first order **actually filled**, not to what was asked for, and grows with each further fill. An entry for a hundred that fills sixty should be followed by sixty, and a child sized to the hundred would open a new position of forty in the other direction the moment it filled.

    The child is described by a `then` object in the caller's `synthetic` parameters, holding an ordinary order body without a quantity: the quantity is the thing this type works out.
    """

    SYNTHETIC_TYPE = 'oto'

    def run(self, intent, started_at):
        """Places the first order. The child follows when it fills.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker, including one whose `then` is not a usable order.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        # Validated before the first order is sent, so a malformed child is refused while there is
        # still nothing at a broker to be left half done.
        self.child_order(1)

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

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

    def child_order(self, quantity):
        """The order the `then` object describes, for a given quantity.

        Args:
            quantity (int): The quantity, in units.

        Returns:
            PlaceOrderRequest: The child order.

        Raises:
            RefusedRequestError: With HTTP 400 when `then` is missing or is not a usable order body.
        """
        described = self.parent.parameters.get('then')
        if not isinstance(described, dict):
            raise RefusedRequestError.refusal(
                'an oto order needs a then object describing the order to '
                'place once the first one fills',
                400,
            )
        body = dict(self.parent.body)
        body.pop('synthetic', None)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.update(described)
        body['quantity'] = quantity
        body.pop('tag', None)
        return self.read_order(body)

    def on_leg_update(self, leg, changes):
        """Places or grows the child once the first order has filled something.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'entry':
            return
        filled = leg.filled_quantity or 0
        if filled < 1:
            return
        child = None
        for other in self.parent.legs:
            if other.role == 'child':
                child = other
                break
        if child is None:
            self.place_leg('child', self.child_order(filled), None, leg.broker)
            self.record_state('protecting', None)
            self.save()
            return
        if child.is_finished():
            return
        wanted = filled - (child.filled_quantity or 0)
        if wanted != child.quantity and wanted >= 1:
            self.reduce_leg(
                child,
                wanted,
                f'the first order has now filled {filled}, so the child '
                'follows it',
            )
            self.save()
