"""A plain order: one parent, one leg, no reaction to anything that happens afterwards."""

from unified_broker_interface.utilities.order_engine.base import (
    OUTCOME_PARENT_STATES,
    SyntheticOrder,
)


class SimpleOrder(SyntheticOrder):
    """One order sent to one broker, which is what every caller gets unless they ask for something else.

    This is the degenerate path through the parent order state machine, and writing it as a class of its own rather than as a special case inside the engine is what makes a bracket an ordinary member of the same family rather than an exception. It records the same events, in the same order, as a type with five legs would.

    It reacts to nothing. Once the broker has answered, the parent is `working` if the order was accepted, `rejected` if the broker refused it, or `failed` if the outcome is unknown. A later stage teaches it to follow the order's fills; until then the order update stream is not read for it and `working` is where it stops.
    """

    SYNTHETIC_TYPE = 'simple'

    def run(self, intent, started_at):
        """Places the caller's order and answers the waiting API worker.

        A price or quantity reference is turned into a real number first, so what is recorded and what is sent are the numbers, not the instruction that produced them. A dry run is answered without recording anything, because nothing happened: no order exists, so there is no parent for recovery to find and nothing for a later reader to be misled by.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
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
        self.record_state(
            OUTCOME_PARENT_STATES.get(outcome, 'failed'),
            body.get('status_message'),
        )
        self.save()

        body['parent_id'] = self.parent.parent_order_id
        return body, status
