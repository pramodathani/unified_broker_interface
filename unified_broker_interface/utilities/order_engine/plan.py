"""An order described as a plan of parts, which the composable synthetic orders are built on."""

import copy

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import (
    OUTCOME_PARENT_STATES,
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.either_part import (
    EitherPart,
)
from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    ReduceOnlyCheck,
)


class PlanOrder(SyntheticOrder):
    """An order whose `synthetic.plan` describes it as a tree of parts, rather than naming one of the fixed types.

    This is the composable orders design as far as it is built. The plan is read and checked in full and every problem is answered at once. Its orders can wait for a trigger, protect a position and be priced by one pricing rule, and they can be joined: `then` starts a child from what a first plan filled, and `either` runs several plans at once, cancelling or reducing the others when one fills. Presets named after the existing types stand for slot values or, for bracket, cover, OCO, OTO and a hidden stop with a backstop, for whole joins.

    The caller's plan stays in `parameters['plan']` exactly as it was sent. What the engine learns while running lives in `parameters['parts']`, one record per part path: `state` (`pending`, `waiting`, `working` or `done`), once done its `reason`, a `target` quantity when a join set one, the trigger's `memory`, and `fired_at`. Changes of state are recorded with `record_parameters`, so recovery replays them, and everything is visible through `GET /api/orders/parents`.

    After every event the whole tree is settled: each join brings its children in line with the fills as they are now. Settling from the current fills rather than adding up changes is what keeps a repeated or late update from being counted twice. The parent ends when the root part is done: `completed` when anything traded, `rejected` when a broker refused an order and nothing traded, and `cancelled` otherwise.
    """

    SYNTHETIC_TYPE = 'plan'
    WANTS_PRICES = True

    def _read_plan(self):
        """Reads the caller's plan into its root part.

        Returns:
            tuple: The root part and the reader's warnings (list).

        Raises:
            RefusedRequestError: With HTTP 400 and every problem in `problems` when the plan cannot run.
        """
        reader = PlanReader(
            str(self.parent.body.get('transaction_type') or '').strip().upper(),
        )
        root = reader.read(self.parent.parameters.get('plan'))
        if root is None:
            raise RefusedRequestError.refusal(
                'the plan cannot run; every problem found is listed in problems',
                400,
                problems=reader.problems,
            )
        return root, reader.warnings

    def run(self, intent, started_at):
        """Checks the plan, then starts it: orders without a trigger are placed now, and the rest wait.

        A dry run is answered with the broker request the caller's order would be sent as and the plan as it would run, with every default written out, and records nothing. An order that protects a position on its own is refused when no position is held on the caller's side, because it would open one.

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

        protecting = root.standalone_protecting_parts()
        if protecting:
            self._refuse_without_position(protecting[0], order)
        records = {}
        needs_prices = False
        watched = []
        for part in root.order_parts():
            record = {
                'state': 'pending',
            }
            if part.trigger is not None:
                memory = {}
                part.prepare(self, memory)
                record['memory'] = memory
            if part.pricing.moves():
                record['moves'] = True
            if part.execution.paced_by_ticks():
                record['paced'] = True
            records[part.path] = record
            if part.needs_prices():
                needs_prices = True
            for instrument_id in part.instruments():
                if instrument_id not in watched:
                    watched.append(instrument_id)
        if needs_prices:
            self.remember_tick_size(order)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['parts'] = records
        if watched:
            self.parent.parameters['watch_instrument_ids'] = watched
        self.record_received()

        quotes = {}
        if needs_prices:
            quotes = self.quotes_now()
        placed = root.start(self, None, started_at, quotes)
        placed = placed + root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        return self._answer(root, placed, warnings)

    def _answer(self, root, placed, warnings):
        """The answer to the caller once the plan has started.

        A plan that placed exactly one order at its root answers with that order's broker answer, as a plain order does. A plan that placed nothing answers `202 armed`. Any other answers with `legs`, one entry per order placed.

        Args:
            root (object): The root part.
            placed (list): One `(path, answer, status)` per order placed.
            warnings (list): The reader's warnings.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        if not placed:
            answer = {
                'broker': None,
                'instrument_id': self.parent.instrument_id,
                'parent_id': self.parent.parent_order_id,
                'tag': self.parent.tag,
                'outcome': 'armed',
                'order_id': None,
                'status_message': 'the plan is recorded and its orders will be placed when their triggers hold',
                'skipped': [],
            }
            status = 202
        elif len(placed) == 1 and placed[0][0] == root.path:
            answer = placed[0][1]
            status = placed[0][2]
        else:
            legs = []
            outcome = None
            status = None
            broker = None
            for path, body, leg_status in placed:
                legs.append({
                    'path': path,
                    'outcome': body.get('outcome'),
                    'order_id': body.get('order_id'),
                    'status_message': body.get('status_message'),
                })
                if broker is None:
                    broker = body.get('broker')
                if outcome != 'accepted':
                    outcome = body.get('outcome')
                    status = leg_status
            answer = {
                'broker': broker,
                'instrument_id': self.parent.instrument_id,
                'tag': self.parent.tag,
                'outcome': outcome,
                'legs': legs,
                'status_message': None,
                'skipped': [],
            }
        answer['parent_id'] = self.parent.parent_order_id
        if warnings:
            answer['warnings'] = warnings
        return answer, status

    def _refuse_without_position(self, part, order):
        """Refuses a part that protects a position when none is held on the caller's side.

        Args:
            part (OrderPart): The protecting part.
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
                    'path': part.path,
                    'rule': 'protect_needs_position',
                    'message': f'this order protects a position opened with a {order.transaction_type}, and the position held is {held}',
                },
            ],
        )

    def quotes_now(self):
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

    def _after_placing(self, placed):
        """Moves the parent to `working` once any order is accepted, or records why none was.

        Args:
            placed (list): One `(path, answer, status)` per order just placed.

        Returns:
            None: This method returns nothing.
        """
        if not placed:
            return
        outcomes = []
        for _, body, _ in placed:
            outcomes.append(body.get('outcome'))
        if 'accepted' in outcomes:
            state = 'working'
            message = None
        else:
            state = OUTCOME_PARENT_STATES.get(outcomes[0], 'failed')
            message = placed[0][1].get('status_message')
        if self.parent.state != state and self.parent.can_change_to(state):
            self.record_state(state, message)

    def _finish_if_done(self, root):
        """Ends the parent once the root part is done.

        Args:
            root (object): The root part.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.is_terminal() or not root.is_done(self):
            return
        traded = 0
        rejected = False
        for leg in self.parent.legs:
            traded = traded + (leg.filled_quantity or 0)
            if leg.state == 'rejected':
                rejected = True
        if traded > 0:
            state = 'completed'
        elif rejected:
            state = 'rejected'
        else:
            state = 'cancelled'
        if self.parent.can_change_to(state):
            self.record_state(state, f'every part of the plan is done, with {traded} traded')

    def _parent_join(self, root, path):
        """The join that holds a part directly.

        Args:
            root (object): The root part.
            path (str): The part's path.

        Returns:
            object | None: The join, or None for the root.
        """
        waiting = [
            root,
        ]
        while waiting:
            node = waiting.pop(0)
            for member in node.members():
                if member.path == path:
                    return node
                waiting.append(member)
        return None

    def on_price_tick(self, quotes, now):
        """Places every waiting order whose trigger holds on this tick, then settles the plan.

        An order whose join cancels before sending is sent only once every sibling's resting order has been cancelled; otherwise it tries again on the next tick. A working order whose pricing moves, such as a trailing stop, is then moved if the tick calls for it.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order was placed or moved on this tick.
        """
        records = self.parent.parameters.get('parts') or {}
        waiting_paths = []
        moving_paths = []
        paced_paths = []
        for path, record in records.items():
            if record.get('state') == 'waiting':
                waiting_paths.append(path)
            if record.get('state') == 'working' and record.get('moves'):
                moving_paths.append(path)
            if record.get('state') == 'working' and record.get('paced'):
                paced_paths.append(path)
        if not waiting_paths and not moving_paths and not paced_paths:
            return False
        root, _ = self._read_plan()
        placed = []
        memory_changed = False
        for part in root.order_parts():
            if part.path not in waiting_paths:
                continue
            record = self.part_record(part.path)
            if record.get('state') != 'waiting':
                continue
            memory = copy.deepcopy(record.get('memory') or {})
            triggered = part.is_triggered(self, memory, quotes, now)
            if memory != (record.get('memory') or {}):
                record['memory'] = memory
                self.set_part_record(part.path, record, None)
                memory_changed = True
            if not triggered:
                continue
            join = self._parent_join(root, part.path)
            if isinstance(join, EitherPart) and join.cancel_before_send:
                if not join.cancel_siblings(
                    self,
                    join.child_index(part.path),
                    f'{part.path} is about to be sent, so its siblings are cancelled first',
                ):
                    continue
            record = self.part_record(part.path)
            record['fired_at'] = now
            self.set_part_record(part.path, record, None)
            sent = part.send(self, None, quotes, now)
            record = self.part_record(part.path)
            if not sent and record.get('state') == 'waiting':
                record.pop('fired_at', None)
                self.set_part_record(part.path, record, None)
            if not sent and record.get('state') == 'working':
                memory_changed = True
            placed = placed + sent
        for part in root.order_parts():
            if part.path in paced_paths:
                placed = placed + part.send_due(self, None, quotes, now)
        moved = False
        for part in root.order_parts():
            if part.path in moving_paths and part.move(self, quotes):
                moved = True
        if not placed and not moved:
            if memory_changed or moving_paths or paced_paths:
                self.save()
            return False
        placed = placed + root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        return True

    def closes_position(self, role):
        """Whether a leg closes a position, which a leg of a `protect` order does.

        Args:
            role (str): The leg's role, which is its part's path.

        Returns:
            bool: True when the leg closes a position.
        """
        if super().closes_position(role):
            return True
        root, _ = self._read_plan()
        for part in root.order_parts():
            if part.path == role:
                return part.closes_position()
        return False

    def on_leg_update(self, leg, changes):
        """Settles the plan after a broker order changed, which may start, resize or cancel other orders, and ends the parent once the plan is done.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        root, _ = self._read_plan()
        placed = root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()

    def finish_cancelling(self):
        """Ends a parent the caller is cancelling, and marks every part not yet done as done.

        Returns:
            bool: True when the parent was ended on this call.
        """
        ended = super().finish_cancelling()
        if ended:
            root, _ = self._read_plan()
            for part in root.order_parts():
                record = self.part_record(part.path)
                if record.get('state') == 'done':
                    continue
                record['state'] = 'done'
                record['reason'] = part.done_reason(self.parent) or 'cancelled'
                self.set_part_record(
                    part.path,
                    record,
                    f'the plan\'s {part.path} part is done: {record["reason"]}',
                )
            self.save()
        return ended

    def part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record, empty when the part has none.
        """
        parts = self.parent.parameters.get('parts') or {}
        return copy.deepcopy(parts.get(path) or {})

    def set_part_record(self, path, record, message):
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
