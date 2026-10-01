"""An order described as a plan of parts, which the composable synthetic orders are built on."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import (
    OUTCOME_PARENT_STATES,
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)

PARENT_STATES_BY_REASON = {
    'filled': 'completed',
    'partly_filled': 'completed',
    'cancelled': 'cancelled',
    'refused': 'rejected',
}


class PlanOrder(SyntheticOrder):
    """An order whose `synthetic.plan` describes it as a tree of parts, rather than naming one of the fixed types.

    This is the first stage of the composable orders design: the plan is read and checked in full, every problem is answered at once, each part keeps its state under its own path in the parent's parameters, and the parent ends when the root part is done. A plan can so far hold one order built from the `simple` preset; the joins and the other presets come in later stages.

    The caller's plan stays in `parameters['plan']` exactly as it was sent. What the engine learns while running lives in `parameters['parts']`, one entry per part path holding its `state` (`working` or `done`) and, once done, its `reason`. Both are recorded with `record_parameters`, so recovery replays them, and both are visible through `GET /api/orders/parents`.
    """

    SYNTHETIC_TYPE = 'plan'

    def _read_plan(self):
        """Reads the caller's plan into its root part.

        Returns:
            OrderPart: The root part.

        Raises:
            RefusedRequestError: With HTTP 400 and every problem in `problems` when the plan cannot run.
        """
        reader = PlanReader()
        root = reader.read(self.parent.parameters.get('plan'))
        if root is None:
            raise RefusedRequestError.refusal(
                'the plan cannot run; every problem found is listed in problems',
                400,
                problems=reader.problems,
            )
        return root

    def run(self, intent, started_at):
        """Checks the plan, then starts its root part and answers with what the broker said.

        A dry run is answered with the first broker request that would be sent and the plan as it would run, with every default written out, and records nothing.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a plan or an order answered without calling a broker.
        """
        root = self._read_plan()
        order = self.concrete_order(self.read_order(self.parent.body))
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
                self.parent.body.get('broker'),
            )
            body, status = self.placement.dry_run_answer(prepared, started_at)
            body['plan'] = root.expanded()
            return body, status

        self.record_received()
        self._set_part_state(root.path, 'working', None)
        self.save()

        body, status = root.start(self, started_at)
        outcome = body.get('outcome')
        if outcome == 'rejected':
            self._set_part_state(root.path, 'done', 'refused')
        self.record_state(
            OUTCOME_PARENT_STATES.get(outcome, 'failed'),
            body.get('status_message'),
        )
        self.save()

        body['parent_id'] = self.parent.parent_order_id
        return body, status

    def on_leg_update(self, leg, changes):
        """Ends the root part, and the parent with it, once all of the root part's broker orders have finished.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        root = self._read_plan()
        if leg.role != root.path:
            return
        reason = root.done_reason(self.parent)
        if reason is None:
            return
        self._set_part_state(root.path, 'done', reason)
        state = PARENT_STATES_BY_REASON[reason]
        if self.parent.can_change_to(state):
            self.record_state(
                state,
                f'the plan\'s {root.path} order is done: {reason}',
            )
        self.save()

    def finish_cancelling(self):
        """Ends a parent the caller is cancelling, and marks the root part done once it has.

        Returns:
            bool: True when the parent was ended on this call.
        """
        ended = super().finish_cancelling()
        if ended:
            root = self._read_plan()
            reason = root.done_reason(self.parent) or 'cancelled'
            self._set_part_state(root.path, 'done', reason)
            self.save()
        return ended

    def _set_part_state(self, path, state, reason):
        """Records one part's state in the parent's parameters.

        Args:
            path (str): The part's path.
            state (str): `working` or `done`.
            reason (str | None): Why a done part is done, or None.

        Returns:
            None: This method returns nothing.
        """
        parts = dict(self.parent.parameters.get('parts') or {})
        part_state = {
            'state': state,
        }
        if reason is not None:
            part_state['reason'] = reason
        if parts.get(path) == part_state:
            return
        parts[path] = part_state
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['parts'] = parts
        if reason is None:
            message = f'the plan\'s {path} part is {state}'
        else:
            message = f'the plan\'s {path} part is {state}: {reason}'
        self.record_parameters(message)
