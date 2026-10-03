"""An order described as a plan of parts, which the composable synthetic orders are built on."""

import copy
import time

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
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.from_fill_pricing import (
    FromFillPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.native_stop_pricing import (
    NativeStopPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.paper_venue import (
    PaperVenue,
)
from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)
from unified_broker_interface.utilities.order_engine.utilities.pre_open_venue import (
    PreOpenVenue,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    ReduceOnlyCheck,
)
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)


class PlanOrder(SyntheticOrder):
    """An order whose `synthetic.plan` describes it as a tree of parts, rather than naming one of the fixed types.

    This is the composable orders design. The plan is read and checked in full and every problem is answered at once. Its orders fill the slots of trigger, side, quantity, pricing, execution, guards, lifetime and venue, and they can be joined: `then` starts a child from what a first plan filled, `either` runs several plans at once, cancelling or reducing the others when one fills, `together` runs them side by side, `sequence` one after another, `repeat` sends one order again on a schedule, and `using` runs every piece an execution would send as a whole plan. Every one of the existing synthetic types has a preset, standing for slot values, for a whole join, or, for the types no join expresses, for a part kept whole.

    The caller's plan stays in `parameters['plan']` exactly as it was sent. What the engine learns while running lives in `parameters['parts']`, one record per part path: `state` (`pending`, `waiting`, `working` or `done`), once done its `reason`, a `target` quantity when a join set one, the trigger's `memory`, and `fired_at`. Changes of state are recorded with `record_parameters`, so recovery replays them, and everything is visible through `GET /api/orders/parents`.

    After every event the whole tree is settled: each join brings its children in line with the fills as they are now. Settling from the current fills rather than adding up changes is what keeps a repeated or late update from being counted twice. The parent ends when the root part is done: `completed` when anything traded, `rejected` when a broker refused an order and nothing traded, and `cancelled` otherwise.
    """

    SYNTHETIC_TYPE = 'plan'
    WANTS_PRICES = True
    WANTS_CLOCK = True
    CARRIES_OVERNIGHT = True
    group_margin_legs = None

    @classmethod
    def carries_parent_overnight(cls, parent):
        """Whether recovery should rebuild a plan from before today, which it should only for a plan marked as outliving the day when it was placed.

        Every plan's events are read from the carry window, but a plan without a lifetime of days is a day's plan, and rebuilding it would revive yesterday's waiting orders and let them fire.

        Args:
            parent (ParentOrder): The parent rebuilt from the record.

        Returns:
            bool: True when the plan was marked `carries_overnight`.
        """
        return parent.parameters.get('carries_overnight') is True

    def _read_plan(self):
        """Reads the caller's plan into its root part.

        Returns:
            tuple: The root part and the reader's warnings (list).

        Raises:
            RefusedRequestError: With HTTP 400 and every problem in `problems` when the plan cannot run.
        """
        reader = PlanReader(
            str(self.parent.body.get('transaction_type') or '').strip().upper(),
            self.parent.body,
            self.parent.parameters.get('hold_limits'),
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
            self._refuse_without_position(protecting[0])
        records = {}
        carries_overnight = False
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
            if part.venue is not None:
                part.venue.check(part.context(self))
            if part.fill_ratio is not None:
                part.fill_ratio.check(part.context(self))
            pricing_memory = part.prepared_pricing_memory(self)
            if pricing_memory:
                record['pricing_memory'] = pricing_memory
            own_memory = part.prepared_own_memory(self)
            if own_memory:
                record['own_memory'] = own_memory
            ends_at = part.lifetime_ends_at(self)
            if ends_at is not None:
                record['ends_at'] = ends_at
            if part.lifetime is not None and part.lifetime.when is not None:
                record['ends_when'] = True
            if part.lifetime is not None and part.lifetime.after_days is not None:
                carries_overnight = True
            if part.spans_days:
                carries_overnight = True
            if part.lifetime is not None and part.lifetime.when is not None:
                lifetime_memory = {}
                part.lifetime.when.prepare(part.context(self), lifetime_memory)
                if lifetime_memory:
                    record['lifetime_memory'] = lifetime_memory
            if part.moves_on_ticks():
                record['moves'] = True
            if part.execution.paced_by_ticks():
                record['paced'] = True
            records[part.path] = record
            if part.needs_prices():
                needs_prices = True
            if isinstance(part.pricing, FromFillPricing):
                needs_prices = True
            for instrument_id in part.instruments():
                if instrument_id not in watched:
                    watched.append(instrument_id)
        if needs_prices:
            self.remember_tick_size(order)
            self._remember_tick_sizes(root)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['parts'] = records
        if carries_overnight:
            self.parent.parameters['carries_overnight'] = True
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

        A plan that placed exactly one order at its root answers with that order's broker answer, as a plain order does. A plan whose order a guard refused, such as a post-only limit that would have crossed, answers `409` with the guard's reason. A plan that placed nothing else answers `202 armed`. Any other answers with `legs`, one entry per order placed, and an outcome combined as today's types combine several orders: `accepted` when all were, `partial` with 207 when some were, and otherwise `rejected` or `unknown`.

        Args:
            root (object): The root part.
            placed (list): One `(path, answer, status)` per order placed.
            warnings (list): The reader's warnings.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        refusal = self._guard_refusal(root)
        if not placed and refusal is not None:
            answer = {
                'broker': None,
                'instrument_id': self.parent.instrument_id,
                'tag': self.parent.tag,
                'outcome': 'rejected',
                'order_id': None,
                'status_message': refusal,
                'skipped': [],
            }
            status = 409
        elif not placed:
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
            outcomes = []
            statuses = []
            broker = None
            for path, body, leg_status in placed:
                legs.append({
                    'path': path,
                    'instrument_id': body.get('instrument_id'),
                    'outcome': body.get('outcome'),
                    'order_id': body.get('order_id'),
                    'status_message': body.get('status_message'),
                })
                outcomes.append(body.get('outcome'))
                statuses.append(leg_status)
                if broker is None:
                    broker = body.get('broker')
            outcome, status = self.combined_answer(outcomes, statuses)
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

    def _remember_tick_sizes(self, root):
        """Works out the tick size of every other instrument a priced order of the plan trades, and keeps them on the parent beside the parent's own.

        Args:
            root (object): The root part.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when the brokers do not agree on a tick size for one of them.
        """
        tick_sizes = {}
        for part in root.order_parts():
            context = part.context(self)
            if context.is_parents_instrument() or not part.needs_prices():
                continue
            instrument, _, _ = self.placement.market_context(context.instrument_id, False, False)
            tick_size = self.read_order(context.body).agreed_tick_size(instrument.handles)
            if tick_size is None:
                raise RefusedRequestError.refusal(
                    'an order of this plan works its prices out from the live quote, which needs a tick size the brokers agree on, and there is none for its instrument',
                    503,
                    instrument_id=context.instrument_id,
                )
            tick_sizes[context.instrument_id] = str(tick_size)
        if tick_sizes:
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['tick_sizes'] = tick_sizes

    def _refuse_without_position(self, part):
        """Refuses a part that protects a position when none is held on its instrument on the side that opened it.

        Args:
            part (OrderPart): The protecting part.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 409 when no position is held on that side.
        """
        context = part.context(self)
        order = self.read_order(context.body)
        held = ReduceOnlyCheck(self.placement).held(
            context.instrument_id,
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
        """The quotes of this parent's instrument and of every instrument the plan watches, as they are now, for pricing an order placed outside a tick.

        Returns:
            dict: Each instrument id to its quote, which may be None.

        Raises:
            RefusedRequestError: When an instrument cannot be read, such as one that is not mapped.
        """
        wanted = [
            self.parent.instrument_id,
        ]
        for instrument_id in self.parent.parameters.get('watch_instrument_ids') or []:
            if instrument_id not in wanted:
                wanted.append(instrument_id)
        quotes = {}
        for instrument_id in wanted:
            _, quote, _ = self.placement.market_context(
                instrument_id,
                True,
                False,
            )
            quotes[instrument_id] = quote
        return quotes

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

    def _after_first_moves(self):
        """Moves the parent out of `received` once a part has placed the plan's first orders on a tick rather than when it started, as an exposure hedge does.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.state != 'received' or not self.parent.legs:
            return
        placed = []
        for leg in self.parent.legs:
            answer = {
                'outcome': leg.outcome,
                'status_message': leg.status_message,
            }
            placed.append((leg.role, answer, None))
        self._after_placing(placed)

    def _finish_if_done(self, root):
        """Ends the parent once the root part is done.

        A plan that only closed positions and found none held ends `completed`, as today's close types do, even straight from `received`, which the usual state changes do not allow.

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
        if self._guard_refusal(root) is not None:
            rejected = True
        nothing_held = False
        for part in root.order_parts():
            record = self.part_record(part.path)
            if record.get('reason') == 'nothing_held':
                nothing_held = True
            traded = traded + (record.get('paper_filled') or 0)
        if traded > 0 or (nothing_held and not rejected):
            state = 'completed'
        elif rejected:
            state = 'rejected'
        else:
            state = 'cancelled'
        closed_nothing = nothing_held and traded == 0 and not rejected
        if self.parent.can_change_to(state) or closed_nothing:
            self.record_state(state, f'every part of the plan is done, with {traded} traded')

    def _guard_refusal(self, root):
        """Why a guard refused an order of the plan without sending it, when one did.

        Args:
            root (object): The root part.

        Returns:
            str | None: The guard's reason, or None when no guard refused an order.
        """
        for part in root.order_parts():
            record = self.part_record(part.path)
            if record.get('reason') == 'refused' and record.get('message'):
                return record['message']
        return None

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
        if self._end_lifetimes(quotes, now):
            return True
        records = self.parent.parameters.get('parts') or {}
        waiting_paths = []
        moving_paths = []
        paced_paths = []
        for path, record in records.items():
            if record.get('state') == 'waiting':
                waiting_paths.append(path)
            if record.get('state') == 'working' and record.get('moves') and not record.get('ended'):
                moving_paths.append(path)
            if record.get('state') == 'working' and record.get('paced'):
                paced_paths.append(path)
        if not waiting_paths and not moving_paths and not paced_paths:
            return False
        root, _ = self._read_plan()
        placed, memory_changed, ended = self._fire_waiting(root, waiting_paths, quotes, now, False)
        for part in root.order_parts():
            if part.path in paced_paths:
                placed = placed + part.send_due(self, None, quotes, now)
        moved = False
        for part in root.order_parts():
            if part.path in moving_paths and part.move(self, quotes, now):
                moved = True
        if moved:
            self._after_first_moves()
        if not placed and not moved and not ended:
            if memory_changed or moving_paths or paced_paths:
                self.save()
            return False
        placed = placed + root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        return True

    def _fire_waiting(self, root, waiting_paths, quotes, now, timed_only):
        """Sends every waiting order whose trigger holds now.

        An order whose join cancels before sending is sent only once every sibling's resting order has been cancelled; otherwise it tries again on the next tick. A paper order is never sent; it takes whatever more its queue estimate has filled. An order held until its limit is marketable records, as it fires, how much a resting order would have filled while it was held, as `missed_quantity`.

        Args:
            root (object): The root part.
            waiting_paths (list): The paths of the orders waiting for their trigger.
            quotes (dict | None): The quotes the tick carried, or None on a clock tick, when they are read only for an order that fires and prices itself.
            now (float): The Unix time of the tick.
            timed_only (bool): Whether to look only at orders whose trigger needs no prices, as on a clock tick.

        Returns:
            tuple: The orders placed, as `(path, answer, status)`; whether any trigger's memory changed (bool); and whether an order fired and ended without placing anything, or filled on paper (bool).
        """
        placed = []
        memory_changed = False
        ended = False
        for part in root.order_parts():
            if part.path not in waiting_paths:
                continue
            if timed_only and part.trigger is not None and part.trigger.needs_prices():
                continue
            record = self.part_record(part.path)
            if record.get('state') != 'waiting':
                continue
            if isinstance(part.venue, PaperVenue):
                if part.venue.fill(self, part):
                    ended = True
                continue
            memory = copy.deepcopy(record.get('memory') or {})
            triggered = part.is_triggered(self, memory, quotes or {}, now)
            if memory != (record.get('memory') or {}):
                record['memory'] = memory
                self.set_part_record(part.path, record, None)
                memory_changed = True
            if not triggered:
                continue
            if isinstance(part.venue, PreOpenVenue) and part.venue.has_closed(part.context(self), now):
                record = self.part_record(part.path)
                record['state'] = 'done'
                record['reason'] = 'expired'
                record['message'] = 'the pre-open stopped taking this order before the engine could send it, so it was not sent into continuous trading'
                self.set_part_record(part.path, record, f'the plan\'s {part.path} part is done: {record["message"]}')
                ended = True
                continue
            join = self._parent_join(root, part.path)
            if isinstance(join, EitherPart) and join.cancel_before_send:
                if not join.cancel_siblings(
                    self,
                    join.child_index(part.path),
                    f'{part.path} is about to be sent, so its siblings are cancelled first',
                ):
                    continue
            sending_quotes = quotes
            if sending_quotes is None:
                sending_quotes = {}
                if part.needs_prices():
                    try:
                        sending_quotes = self.quotes_now()
                    except RefusedRequestError as refusal:
                        self.logger.warning(f'Parent {self.parent.parent_order_id} could not read the quotes to send {part.path}: {refusal.body.get("error")}')
                        continue
            record = self.part_record(part.path)
            record['fired_at'] = now
            if isinstance(part.trigger, LimitMarketableCondition):
                missed = (part.trigger.estimate(self, part.path) or {}).get('queue_filled')
                if isinstance(missed, int):
                    record['missed_quantity'] = missed
            self.set_part_record(part.path, record, None)
            sent = part.send(self, None, sending_quotes, now)
            record = self.part_record(part.path)
            if not sent and record.get('state') == 'waiting':
                record.pop('fired_at', None)
                self.set_part_record(part.path, record, None)
            if not sent and record.get('state') == 'working':
                memory_changed = True
            if not sent and record.get('state') == 'done':
                ended = True
            placed = placed + sent
        return placed, memory_changed, ended

    def on_clock_tick(self, now):
        """Ends every order whose lifetime is up and sends every order waiting only for a time, even when its instrument sent no price tick.

        Orders whose trigger reads prices are left to the price ticks, because some of those triggers count ticks. Orders sent in pieces on later ticks, such as a TWAP or a daily stop, are sent their due pieces too, priced from the quotes as they are now, as today's timed types are sent theirs on the clock.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order's lifetime ended or an order was sent.
        """
        if self._end_lifetimes(None, now):
            return True
        waiting_paths = []
        paced_paths = []
        for path, record in (self.parent.parameters.get('parts') or {}).items():
            if record.get('state') == 'waiting':
                waiting_paths.append(path)
            if record.get('state') == 'working' and record.get('paced'):
                paced_paths.append(path)
        if not waiting_paths and not paced_paths:
            return False
        root, _ = self._read_plan()
        placed, memory_changed, ended = self._fire_waiting(root, waiting_paths, None, now, True)
        for part in root.order_parts():
            if part.path not in paced_paths:
                continue
            quotes = {}
            if part.needs_prices():
                try:
                    quotes = self.quotes_now()
                except RefusedRequestError as refusal:
                    self.logger.warning(f'Parent {self.parent.parent_order_id} could not read the quotes to send {part.path}: {refusal.body.get("error")}')
                    continue
            placed = placed + part.send_due(self, None, quotes, now)
        if not placed and not ended:
            if memory_changed:
                self.save()
            return False
        placed = placed + root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        return True

    def _end_lifetimes(self, quotes, now):
        """Ends every order whose lifetime is up, then settles the plan and ends the parent if it is done.

        Args:
            quotes (dict | None): The quotes the tick carried, or None on a clock tick, when they are read only if an order is to be made marketable.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order's lifetime ended.
        """
        due = False
        for record in (self.parent.parameters.get('parts') or {}).values():
            ends_at = record.get('ends_at')
            if record.get('ended') or record.get('state') == 'done':
                continue
            if record.get('ends_when') or (ends_at is not None and now >= ends_at):
                due = True
        if not due:
            return False
        root, _ = self._read_plan()
        if quotes is None:
            quotes = {}
            for part in root.order_parts():
                if part.lifetime is not None and part.lifetime.on_end == 'marketable':
                    try:
                        quotes = self.quotes_now()
                    except RefusedRequestError as refusal:
                        self.logger.warning(f'Parent {self.parent.parent_order_id} could not read the quote to make its order marketable: {refusal.body.get("error")}')
                    break
        ended = False
        for part in root.order_parts():
            if part.end_lifetime(self, quotes, now):
                ended = True
        if not ended:
            return False
        placed = root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        return True

    def modify_held(self, price, quantity, dry_run):
        """Changes the price or quantity of the order this plan holds in the engine on a `limit_marketable` trigger, without sending anything to a broker.

        It keeps the rules of today's virtual limit type. The change is kept in the order's part record, which its context writes over the body, and in the held terms its trigger keeps, so `bin/unified/orders/virtual_book` starts a fresh queue estimate, as a changed price at the exchange goes to the back of the queue. Only a plan holding exactly one such order can be changed this way.

        Args:
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 409 when the plan has finished, holds no such order or several, its order has already been sent, or a paper order would be cut below what it has filled; 400 when the price is not a whole number of ticks or the quantity is not a whole number of lots at any broker.
        """
        if self.parent.is_terminal():
            raise RefusedRequestError.refusal(f'the order is already {self.parent.state}', 409, parent_id=self.parent.parent_order_id)
        root, _ = self._read_plan()
        held = []
        sent = []
        for part in root.order_parts():
            if not isinstance(part.trigger, LimitMarketableCondition):
                continue
            if self.part_record(part.path).get('state') == 'waiting':
                held.append(part)
            else:
                sent.append(part)
        if not held and sent:
            detail = {
                'parent_id': self.parent.parent_order_id,
            }
            legs = sent[0].own_legs(self.parent)
            if legs:
                detail['broker'] = legs[-1].broker
                detail['order_id'] = legs[-1].broker_order_id
            raise RefusedRequestError.refusal('the order has already been sent to a broker, so change it with broker and order_id instead of parent_id', 409, **detail)
        if len(held) != 1:
            if not held:
                return super().modify_held(price, quantity, dry_run)
            raise RefusedRequestError.refusal(f'the plan holds {len(held)} orders on limit_marketable triggers, and changing one of several by parent_id is not built', 409, parent_id=self.parent.parent_order_id)
        return self._change_held_part(held[0], price, quantity, dry_run)

    def _check_ticks_and_lots(self, context, prices, order):
        """Refuses prices that are not a whole number of ticks, and a quantity that is not a whole number of lots at any broker.

        Args:
            context (OrderContext): The part's context, which knows its instrument and tick size.
            prices (dict): Each changed price's name to its value (decimal.Decimal), or None when it is not changed.
            order (PlaceOrderRequest): The order with the new quantity, checked against each broker's lot size.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 for a price off the tick or a quantity off the lot at every broker.
        """
        tick_size = context.tick_size()
        for name, value in prices.items():
            if tick_size and value is not None and value % tick_size != 0:
                raise RefusedRequestError.refusal(f'{name} must be a whole number of ticks of {format(tick_size.normalize(), "f")}', 400)
        instrument, _, _ = self.placement.market_context(context.instrument_id, False, False)
        problems = []
        for handle in (instrument.handles or {}).values():
            problems.append(order.lot_size_problem(handle))
        if problems and all(problems):
            raise RefusedRequestError.refusal(problems[0], 400)

    def _change_held_part(self, part, price, quantity, dry_run):
        """Changes the price or quantity of one order this plan holds in the engine on a `limit_marketable` trigger.

        A held rung of a Using join was given its share as its target, and a Using join is never resized, so a new quantity becomes the rung's target as well; otherwise the rung would still send the share it was given.

        Args:
            part (OrderPart): The held order.
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the price is not a whole number of ticks or the quantity is not a whole number of lots at any broker, and 409 when a paper order would be cut below what it has filled.
        """
        context = part.context(self)
        current = self.read_order(context.body)
        body = dict(context.body)
        body['price'] = str(price if price is not None else current.price)
        body['quantity'] = quantity if quantity is not None else current.quantity
        changed = self.read_order(body)
        self._check_ticks_and_lots(
            context,
            {
                'price': changed.price,
            },
            changed,
        )
        record = self.part_record(part.path)
        filled = record.get('paper_filled') or 0
        if changed.quantity <= filled:
            raise RefusedRequestError.refusal(f'the paper order has already filled {filled}, so its quantity cannot become {changed.quantity}', 409, parent_id=self.parent.parent_order_id)
        answer = {
            'parent_id': self.parent.parent_order_id,
            'synthetic_type': self.parent.synthetic_type,
            'held': True,
            'price': str(changed.price),
            'quantity': changed.quantity,
        }
        if dry_run:
            answer['dry_run'] = True
            answer['status_message'] = 'the change is valid; nothing was changed'
            return answer, 200
        record['held_price'] = str(changed.price)
        record['held_quantity'] = changed.quantity
        if record.get('piece_quantity') is not None:
            record['target'] = changed.quantity
        memory = record.get('memory') or {}
        trigger_memory = memory.get('trigger') or {}
        terms = dict(trigger_memory.get('held') or {})
        terms['price'] = str(changed.price)
        terms['quantity'] = changed.quantity
        trigger_memory['held'] = terms
        memory['trigger'] = trigger_memory
        record['memory'] = memory
        self.set_part_record(part.path, record, f'the caller changed the held order to {changed.quantity} at {changed.price}')
        self.save()
        answer['outcome'] = 'accepted'
        answer['status_message'] = 'changed while held in the virtual order book; nothing was sent to a broker'
        return answer, 200

    def modify_part(self, path, price, trigger_price, quantity, dry_run):
        """Changes the price, trigger price or quantity of one part of this plan that has not yet sent anything to a broker.

        The new values are kept in the part's record and recorded with an event, so a restart keeps them. A price or trigger price is laid over what the part's pricing gives when the part is sent, so only a part whose pricing gives a fixed price can take one: a plain limit or a native stop, not a peg or a trail, which work out their price from the market when they are sent. A quantity becomes the part's total; an order that closes a position can only be reduced, and a part sized by an earlier part's fills has no total until those fills arrive. A part held on a `limit_marketable` trigger is changed as `modify_held` changes it.

        Args:
            path (str): The part's path, as `GET /api/orders/parents` shows it.
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), 200 once changed or for a dry run.

        Raises:
            RefusedRequestError: With HTTP 404 when the plan has no order part at `path`; 409 when the plan has finished, the part has already sent an order (the answer then names its broker orders), it is kept whole, or a quantity cannot change; 400 when its pricing does not take the price given, a trigger price is given for an order that is not a stop, or a price or quantity is off the tick or lot.
        """
        parent_order_id = self.parent.parent_order_id
        if self.parent.is_terminal():
            raise RefusedRequestError.refusal(f'the order is already {self.parent.state}', 409, parent_id=parent_order_id)
        root, _ = self._read_plan()
        part = None
        for candidate in root.order_parts():
            if candidate.path == path:
                part = candidate
        if part is None:
            raise RefusedRequestError.refusal(f'the plan has no order at part {path}', 404, parent_id=parent_order_id, part=path)
        record = self.part_record(path)
        if record.get('state') not in (None, 'pending', 'waiting'):
            sent = []
            for leg in part.own_legs(self.parent):
                sent.append({
                    'broker': leg.broker,
                    'order_id': leg.broker_order_id,
                })
            raise RefusedRequestError.refusal(f'part {path} is already {record.get("state")}, so change its broker orders with broker and order_id instead', 409, parent_id=parent_order_id, part=path, orders=sent)
        if isinstance(part, WholePart):
            raise RefusedRequestError.refusal(f'part {path} is a {part.name}, which keeps its orders by its own rules, so it cannot be changed before it starts', 409, parent_id=parent_order_id, part=path)
        if record.get('ended'):
            raise RefusedRequestError.refusal(f'part {path} has been cancelled, so it cannot be changed', 409, parent_id=parent_order_id, part=path)
        if isinstance(part.trigger, LimitMarketableCondition) and record.get('state') == 'waiting':
            if trigger_price is not None:
                raise RefusedRequestError.refusal('a held limit order has no trigger price to change', 400, parent_id=parent_order_id, part=path)
            answer, status = self._change_held_part(part, price, quantity, dry_run)
            answer['part'] = path
            return answer, status
        if (price is not None or trigger_price is not None) and not isinstance(part.pricing, (FixedPricing, NativeStopPricing)):
            raise RefusedRequestError.refusal(f'part {path} works out its price from the market when it is sent, so its price cannot be set beforehand', 400, parent_id=parent_order_id, part=path)
        context = part.context(self)
        order_type = str(context.body.get('order_type') or '').upper()
        if isinstance(part.pricing, FixedPricing) and part.pricing.order_type is not None:
            order_type = part.pricing.order_type
        if trigger_price is not None and not isinstance(part.pricing, NativeStopPricing) and order_type not in ('SL', 'SL-M'):
            raise RefusedRequestError.refusal(f'part {path} is not a stop, so it has no trigger price to change', 400, parent_id=parent_order_id, part=path)
        total = part.total(self)
        if quantity is not None:
            if part.opened_by or part.sized_by_fills:
                raise RefusedRequestError.refusal(f'part {path} is sized by what an earlier part fills, so its quantity is not known until then', 409, parent_id=parent_order_id, part=path)
            if part.closes_position() and quantity > total:
                raise RefusedRequestError.refusal(f'an order that closes a position can only be reduced, and {quantity} is more than its {total}', 409, parent_id=parent_order_id, part=path)
            body = dict(context.body)
            body['quantity'] = quantity
            body.pop('quantity_reference', None)
            checked = self.read_order(body)
        else:
            checked = self.read_order(context.body)
        self._check_ticks_and_lots(
            context,
            {
                'price': price,
                'trigger_price': trigger_price,
            },
            checked,
        )
        answer = {
            'parent_id': parent_order_id,
            'synthetic_type': self.parent.synthetic_type,
            'part': path,
            'state': record.get('state') or 'pending',
            'price': str(price) if price is not None else record.get('caller_price'),
            'trigger_price': str(trigger_price) if trigger_price is not None else record.get('caller_trigger_price'),
            'quantity': quantity if quantity is not None else total,
        }
        if dry_run:
            answer['dry_run'] = True
            answer['status_message'] = 'the change is valid; nothing was changed'
            return answer, 200
        changes = []
        if price is not None:
            record['caller_price'] = str(price)
            changes.append(f'price {price}')
        if trigger_price is not None:
            record['caller_trigger_price'] = str(trigger_price)
            changes.append(f'trigger price {trigger_price}')
        if quantity is not None and quantity != total:
            record['caller_change'] = (record.get('caller_change') or 0) + quantity - total
            changes.append(f'quantity {quantity}')
        self.set_part_record(path, record, f'the caller changed the plan\'s {path} part before it was sent: {", ".join(changes) or "nothing"}')
        self.save()
        answer['outcome'] = 'accepted'
        answer['status_message'] = 'changed before it was sent; nothing was sent to a broker'
        return answer, 200

    def cancel_part(self, path, dry_run):
        """Cancels one part of this plan and stops it sending anything more, whether or not it has already sent orders.

        A part whose turn has not come is kept from being sent when it comes, and a part waiting on its trigger is marked done as `cancelled`. A part that has sent orders sends no further piece, such as a TWAP's later slices, and each of its orders still resting is cancelled; it is marked done once the brokers confirm. The plan is then settled, so the rest of it reacts as it does to that part finishing: a bracket whose entry is cancelled before it fills drops its exits. Asking again retries any cancel a broker did not accept.

        Args:
            path (str): The part's path, as `GET /api/orders/parents` shows it.
            dry_run (bool): Whether to check the cancel without making it.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int): 200 once every resting order's cancel was accepted, when none was resting, or for a dry run, and 207 when a broker did not accept a cancel, which leaves that order resting.

        Raises:
            RefusedRequestError: With HTTP 404 when the plan has no order part at `path`, and 409 when the plan or the part has already finished, a part whose turn has not come is already cancelled, or it is a kept-whole part that has not started.
        """
        parent_order_id = self.parent.parent_order_id
        if self.parent.is_terminal():
            raise RefusedRequestError.refusal(f'the order is already {self.parent.state}', 409, parent_id=parent_order_id)
        root, _ = self._read_plan()
        part = None
        for candidate in root.order_parts():
            if candidate.path == path:
                part = candidate
        if part is None:
            raise RefusedRequestError.refusal(f'the plan has no order at part {path}', 404, parent_id=parent_order_id, part=path)
        record = self.part_record(path)
        state = record.get('state') or 'pending'
        if state == 'done':
            raise RefusedRequestError.refusal(f'part {path} is already done: {record.get("reason")}', 409, parent_id=parent_order_id, part=path)
        if state == 'pending' and record.get('ended'):
            raise RefusedRequestError.refusal(f'part {path} is already cancelled, and will not be sent when its turn comes', 409, parent_id=parent_order_id, part=path)
        if state == 'pending' and isinstance(part, WholePart):
            raise RefusedRequestError.refusal(f'part {path} is a {part.name}, which keeps its orders by its own rules, so it cannot be cancelled before it starts; cancel it once it has started, or cancel the whole parent', 409, parent_id=parent_order_id, part=path)
        resting = []
        for leg in part.own_legs(self.parent):
            if not leg.is_finished() and leg.broker_order_id:
                resting.append(leg)
        answer = {
            'parent_id': parent_order_id,
            'synthetic_type': self.parent.synthetic_type,
            'part': path,
            'state': state,
        }
        if dry_run:
            orders = []
            for leg in resting:
                orders.append({
                    'broker': leg.broker,
                    'order_id': leg.broker_order_id,
                })
            answer['orders'] = orders
            answer['dry_run'] = True
            answer['status_message'] = 'the cancel is valid; nothing was cancelled'
            return answer, 200
        part.cancel_for_caller(self, f'the caller cancelled the plan\'s {path} part')
        asked = self.part_record(path).get('cancel_asked') or []
        orders = []
        not_accepted = 0
        for leg in resting:
            accepted = leg.leg_id in asked
            if not accepted:
                not_accepted = not_accepted + 1
            orders.append({
                'broker': leg.broker,
                'order_id': leg.broker_order_id,
                'cancel_accepted': accepted,
            })
        placed = root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()
        answer['orders'] = orders
        if not_accepted:
            answer['outcome'] = 'partial'
            if not_accepted == len(resting):
                answer['outcome'] = 'rejected'
            answer['status_message'] = f'the broker did not accept the cancel of {not_accepted} of its orders, which may still be resting; ask again to retry'
            return answer, 207
        answer['outcome'] = 'accepted'
        if resting:
            answer['status_message'] = 'its resting orders are being cancelled, and it sends nothing more'
        elif state == 'pending':
            answer['status_message'] = 'it will not be sent when its turn comes; nothing was sent to a broker'
        else:
            answer['status_message'] = 'cancelled before it was sent; nothing was sent to a broker'
        return answer, 200

    def _part_for_leg(self, root, leg):
        """The order part that placed a broker order, or None for an order no part placed, such as a lifetime's close.

        Args:
            root (object): The root part.
            leg (OrderLeg): The broker order.

        Returns:
            OrderPart | None: The part.
        """
        for part in root.order_parts():
            if part.path == leg.role:
                return part
        return None

    def outside_change_problem(self, leg, quantity_units):
        """Refuses a caller's change that would raise the quantity of an order closing a position.

        An exit only ever closes what is held. Raising one could leave it larger than the position, and a stop that fills for more than is held opens a new position in the other direction. This keeps the rule of today's linked pair of exits.

        Args:
            leg (OrderLeg): The leg to be changed.
            quantity_units (int | None): The new quantity as the caller gave it, or None when the quantity is not changing.

        Returns:
            str | None: The reason, or None.
        """
        if quantity_units is None or leg.quantity is None or quantity_units <= leg.quantity:
            return None
        if not self.closes_position(leg.role):
            return None
        return f'an order that closes a position can only be reduced, and {quantity_units} is more than its {leg.quantity}'

    def on_leg_modified(self, leg, before):
        """Lets the plan carry on from a change the caller made to one of its broker orders, then settles it so the rest of the plan follows.

        The part that placed the order hands a new price or trigger to its pricing, so a trail, peg, chase or followed price carries on from the caller's value instead of moving it back. A new quantity on an order sent all at once becomes that order's total; under an Either join that reduces, it comes off the quantity every child shares, so the other exits follow it. An order split into pieces keeps its total, and its later pieces make up the difference.

        Args:
            leg (OrderLeg): The leg the caller changed, holding its new values.
            before (dict): What the leg held before, with `quantity`, `price` and `trigger_price`.

        Returns:
            None: This method returns nothing.
        """
        root, _ = self._read_plan()
        part = self._part_for_leg(root, leg)
        if part is None:
            return
        if leg.price != before.get('price') or leg.trigger_price != before.get('trigger_price'):
            try:
                quotes = self.quotes_now()
            except RefusedRequestError as refusal:
                self.logger.warning(f'Parent {self.parent.parent_order_id} could not read the quote to carry on from the caller\'s change: {refusal.body.get("error")}')
                quotes = {}
            part.carry_on(self, leg, before, quotes, time.time())
        old_quantity = before.get('quantity')
        if leg.quantity is not None and old_quantity is not None and leg.quantity != old_quantity and part.keeps_caller_quantity():
            change = leg.quantity - old_quantity
            join = self._parent_join(root, part.path)
            if isinstance(join, EitherPart) and join.sibling_rule == 'reduce':
                join.take_caller_change(self, change)
            else:
                part.take_caller_change(self, change)
        placed = root.settle(self)
        self._after_placing(placed)
        self._finish_if_done(root)
        self.save()

    def closes_position(self, role):
        """Whether a leg closes a position, which a leg of a `protect` order does, and so does the close a lifetime's `close_filled` sends.

        Args:
            role (str): The leg's role, which is its part's path, or the path followed by `.close`.

        Returns:
            bool: True when the leg closes a position.
        """
        if super().closes_position(role):
            return True
        if role.endswith('.close'):
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
