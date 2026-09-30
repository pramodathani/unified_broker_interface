"""An order described as a plan of parts, which the composable synthetic orders are built on."""

import copy

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
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    ReduceOnlyCheck,
)

PARENT_STATES_BY_REASON = {
    'filled': 'completed',
    'partly_filled': 'completed',
    'cancelled': 'cancelled',
    'refused': 'rejected',
}


class PlanOrder(SyntheticOrder):
    """An order whose `synthetic.plan` describes it as a tree of parts, rather than naming one of the fixed types.

    This is the composable orders design as far as it is built: the plan is read and checked in full and every problem is answered at once, each part keeps its state under its own path in the parent's parameters, and the parent ends when the root part is done. A plan holds one order, which may wait for a trigger, protect a position, and be priced by one pricing rule, built from presets or written out as slot values; the joins come in the next stage.

    The caller's plan stays in `parameters['plan']` exactly as it was sent. What the engine learns while running lives in `parameters['parts']`, one entry per part path holding its `state` (`waiting`, `working` or `done`), once done its `reason`, and `memory`, what its trigger has to remember between ticks. A change of state is recorded with `record_parameters`, so recovery replays it, and everything is visible through `GET /api/orders/parents`. A trigger's confirmation count is kept in Redis between ticks but not recorded, as today's price triggers keep theirs.

    Every plan parent is offered price ticks, because a trigger may need them, and a time condition is also checked on those ticks. A parent with nothing waiting answers a tick at once.
    """

    SYNTHETIC_TYPE = 'plan'
    WANTS_PRICES = True

    def _read_plan(self):
        """Reads the caller's plan into its root part.

        Returns:
            tuple: The root part (OrderPart) and the reader's warnings (list).

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
        return root, reader.warnings

    def run(self, intent, started_at):
        """Checks the plan, then either places its order or arms it to wait for its trigger.

        A dry run is answered with the broker request the order would be sent as and the plan as it would run, with every default written out, and records nothing. A part that protects a position is refused when no position is held on the caller's side, because it would open one.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a plan or an order answered without calling a broker.
        """
        root, warnings = self._read_plan()
        order = self.concrete_order(self.read_order(self.parent.body))
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
                self.parent.body.get('broker'),
            )
            body, status = self.placement.dry_run_answer(prepared, started_at)
            body['plan'] = root.expanded()
            if warnings:
                body['warnings'] = warnings
            return body, status

        if root.closes_position():
            self._refuse_without_position(root, order)
        memory = {}
        root.prepare(self, memory)
        if root.needs_prices():
            self.remember_tick_size(order)
        watched = root.instruments()
        if watched:
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['watch_instrument_ids'] = watched
        self.record_received()

        if root.trigger is not None:
            self._set_part_record(
                root.path,
                {
                    'state': 'waiting',
                    'memory': memory,
                },
                f'the plan\'s {root.path} part is waiting for its trigger',
            )
            self.save()
            answer = {
                'broker': None,
                'instrument_id': self.parent.instrument_id,
                'parent_id': self.parent.parent_order_id,
                'tag': self.parent.tag,
                'outcome': 'armed',
                'order_id': None,
                'status_message': 'the plan is recorded and its order will be placed when its trigger holds',
                'skipped': [],
            }
            if warnings:
                answer['warnings'] = warnings
            return answer, 202

        self._set_part_record(
            root.path,
            {
                'state': 'working',
            },
            f'the plan\'s {root.path} part is working',
        )
        self.save()
        placed = root.place(self, started_at, self._quotes_now())
        if placed is None:
            raise RefusedRequestError.refusal(
                'the plan\'s order could not be priced, because the book has no side to price against',
                503,
            )
        body, status = placed
        self._after_placing(root, body)
        body['parent_id'] = self.parent.parent_order_id
        if warnings:
            body['warnings'] = warnings
        return body, status

    def _refuse_without_position(self, root, order):
        """Refuses a part that protects a position when none is held on the caller's side.

        Args:
            root (OrderPart): The part.
            order (PlaceOrderRequest): The caller's order, whose side opened the position.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 409 when no position is held on that side.
        """
        held = ReduceOnlyCheck(self.placement).held(
            self.parent.instrument_id,
            order.product,
        )
        if order.transaction_type == 'BUY' and held > 0:
            return
        if order.transaction_type == 'SELL' and held < 0:
            return
        raise RefusedRequestError.refusal(
            'the plan cannot run; every problem found is listed in problems',
            409,
            problems=[
                {
                    'path': root.path,
                    'rule': 'protect_needs_position',
                    'message': f'this order protects a position opened with a {order.transaction_type}, and the position held is {held}',
                },
            ],
        )

    def _quotes_now(self):
        """This parent's instrument's quote as it is now, for pricing an order placed outside a tick.

        Returns:
            dict: The instrument id to its quote, which may be None.
        """
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        return {
            self.parent.instrument_id: quote,
        }

    def _after_placing(self, root, body):
        """Records what the parent became once the root part's order has been sent.

        Args:
            root (OrderPart): The root part.
            body (dict): The broker's answer.

        Returns:
            None: This method returns nothing.
        """
        outcome = body.get('outcome')
        if outcome == 'rejected':
            self._set_part_record(
                root.path,
                {
                    'state': 'done',
                    'reason': 'refused',
                },
                f'the plan\'s {root.path} part is done: refused',
            )
        self.record_state(
            OUTCOME_PARENT_STATES.get(outcome, 'failed'),
            body.get('status_message'),
        )
        self.save()

    def on_price_tick(self, quotes, now):
        """Places the root part's order on the first tick its trigger holds.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was placed on this tick.
        """
        record = self._part_record('root')
        if record.get('state') != 'waiting':
            return False
        root, _ = self._read_plan()
        memory = copy.deepcopy(record.get('memory') or {})
        triggered = root.is_triggered(self, memory, quotes, now)
        if memory != (record.get('memory') or {}):
            record['memory'] = memory
            self._set_part_record(root.path, record, None)
            self.save()
        if not triggered:
            return False
        placed = root.place(self, None, quotes)
        if placed is None:
            return False
        record['state'] = 'working'
        record['fired_at'] = now
        self._set_part_record(
            root.path,
            record,
            f'the plan\'s {root.path} part\'s trigger held, so its order was placed',
        )
        body, _ = placed
        self._after_placing(root, body)
        return True

    def closes_position(self, role):
        """Whether a leg closes a position, which a leg of a `protect` part does.

        Args:
            role (str): The leg's role, which is its part's path.

        Returns:
            bool: True when the leg closes a position.
        """
        if super().closes_position(role):
            return True
        root, _ = self._read_plan()
        return role == root.path and root.closes_position()

    def on_leg_update(self, leg, changes):
        """Ends the root part, and the parent with it, once all of the root part's broker orders have finished.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        root, _ = self._read_plan()
        if leg.role != root.path:
            return
        reason = root.done_reason(self.parent)
        if reason is None:
            return
        self._set_part_record(
            root.path,
            {
                'state': 'done',
                'reason': reason,
            },
            f'the plan\'s {root.path} part is done: {reason}',
        )
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
            root, _ = self._read_plan()
            reason = root.done_reason(self.parent) or 'cancelled'
            self._set_part_record(
                root.path,
                {
                    'state': 'done',
                    'reason': reason,
                },
                f'the plan\'s {root.path} part is done: {reason}',
            )
            self.save()
        return ended

    def _part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record, empty when the part has none.
        """
        parts = self.parent.parameters.get('parts') or {}
        return dict(parts.get(path) or {})

    def _set_part_record(self, path, record, message):
        """Writes one part's record into the parent's parameters, and records the change when there is a message.

        Args:
            path (str): The part's path.
            record (dict): The part's record.
            message (str | None): Why it changed, for the event log, or None to keep it only in the parameters.

        Returns:
            None: This method returns nothing.
        """
        parts = dict(self.parent.parameters.get('parts') or {})
        if parts.get(path) == record:
            return
        parts[path] = record
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['parts'] = parts
        if message is not None:
            self.record_parameters(message)
