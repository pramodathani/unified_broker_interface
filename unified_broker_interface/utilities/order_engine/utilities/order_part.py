"""One order in a plan: a leaf of the plan's tree, which places its own broker orders and says when it is done."""

import copy
import time

from unified_broker_interface.utilities.order_engine.utilities.all_at_once_execution import (
    AllAtOnceExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.follow_instrument_pricing import (
    FollowInstrumentPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.ladder_execution import (
    LadderExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.order_context import (
    OrderContext,
)

MARKETABLE_BUFFER_TICKS = 2
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}
GROWN_AGAIN_REASONS = (
    'filled',
    'cancelled',
)
NAMED_SIDES = {
    'buy': 'BUY',
    'sell': 'SELL',
}


class OrderPart:
    """One order in a plan, built afresh from the caller's plan on every event, with its state kept by the plan order.

    Every broker order it places carries its path as the leg's role, and it only ever looks at legs with that role, so another part's orders can never be mistaken for its own. That is the rule that lets parts be combined, where today's order types each assume they own every leg of the parent.

    An order with a trigger waits until the trigger holds and then places its order once. `side` is `buy` or `sell` to name the side, `protect` to trade against the position the caller's order opened, which sends the opposite side and counts as closing a position, `same_as_first` to trade on the side the first plan of its Then join filled on, or None for the body's own side. Pricing decides the order type and prices at the moment the order is sent.

    Attributes:
        path (str): Where the part sits in the plan, such as `root`.
        presets (list): The names of the presets it was built from, in order.
        trigger (object | None): The condition it waits for, or None to be placed at once.
        side (str | None): `buy`, `sell`, `protect`, or None for the body's side.
        pricing (object): The pricing that sets the order type and prices.
        keeps_tag (bool): Whether its orders carry the caller's tag, which only the plan's main order does.
        execution (object): How its quantity is cut into pieces and when each is sent.
        cap (CapModifier | None): The worst price its limit may reach, or None.
        post_only (PostOnlyGuard | None): The check that keeps its limit from crossing, or None.
        discretion (DiscretionModifier | None): How far past its visible price it quietly goes, or None.
        lifetime (Lifetime | None): When it stops working and what is done then, or None for the body's validity.
        overrides (dict): Body values of its own, such as `instrument_id`, `quantity` or `transaction_type`, written over the caller's body; empty for an order on the body as it is.
        position (PositionQuantity | None): For the `close` side, how the position it closes is read; None for any other order.
        fill_ratio (FillRatio | FillDelta | None): How the size a Then join hands it is scaled, or None to take it as it is.
        sized_by_fills (bool): Whether it is a Then join's child, sized by the first plan's fills.
        opened_by (list): The paths of the orders whose fills opened the position this order follows, for an order under a Then join; empty otherwise.
        venue (PreOpenVenue | None): Where the order is sent other than the broker selector's continuous market, or None.
        spans_days (bool): Whether the order may go on a later trading day, as a daily Repeat's copies do, which keeps the plan across trading days.
    """

    def __init__(self, path, presets, trigger, side, pricing, keeps_tag=True, execution=None, cap=None, post_only=None, discretion=None, lifetime=None, overrides=None, position=None):
        """Builds the part from values the plan reader has already checked.

        Args:
            path (str): Where the part sits in the plan.
            presets (list): The names of the presets it was built from, in order.
            trigger (object | None): The condition it waits for, or None.
            side (str | None): `buy`, `sell`, `protect`, or None.
            pricing (object): The pricing.
            keeps_tag (bool): Whether its orders carry the caller's tag.
            execution (object | None): How its quantity is sent, or None for all at once.
            cap (CapModifier | None): The worst price its limit may reach, or None.
            post_only (PostOnlyGuard | None): The check that keeps its limit from crossing, or None.
            discretion (DiscretionModifier | None): How far past its visible price it quietly goes, or None.
            lifetime (Lifetime | None): When it stops working and what is done then, or None.
            overrides (dict | None): Body values of its own, or None for none.
            position (PositionQuantity | None): How the position a `close` order closes is read, or None.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.presets = presets
        self.trigger = trigger
        self.side = side
        self.pricing = pricing
        self.keeps_tag = keeps_tag
        if execution is None:
            execution = AllAtOnceExecution()
        self.execution = execution
        self.cap = cap
        self.post_only = post_only
        self.discretion = discretion
        self.lifetime = lifetime
        if overrides is None:
            overrides = {}
        self.overrides = overrides
        self.position = position
        self.fill_ratio = None
        self.sized_by_fills = False
        self.opened_by = []
        self.venue = None
        self.spans_days = False

    def context(self, plan_order):
        """The plan order as this order's pricing, execution and trigger see it: on this order's instrument, with its own body values, a Using join's rung price and share, the limit price of a `fixed` pricing that gives one, and any price or quantity the caller changed while it was held.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            OrderContext: The context.
        """
        body = dict(plan_order.parent.body)
        instrument_id = plan_order.parent.instrument_id
        for name, value in self.overrides.items():
            if name == 'instrument_id':
                instrument_id = value
            else:
                body[name] = value
        record = (plan_order.parent.parameters.get('parts') or {}).get(self.path) or {}
        if record.get('piece_price') is not None:
            body['price'] = record['piece_price']
            body['order_type'] = 'LIMIT'
            body.pop('price_reference', None)
            body.pop('trigger_price', None)
        if record.get('piece_quantity') is not None:
            body['quantity'] = record['piece_quantity']
        if isinstance(self.pricing, FixedPricing) and self.pricing.price is not None and self.pricing.order_type != 'MARKET':
            body['price'] = str(self.pricing.price)
            body['order_type'] = 'LIMIT'
        if record.get('held_price') is not None:
            body['price'] = record['held_price']
        if record.get('held_quantity') is not None:
            body['quantity'] = record['held_quantity']
        return OrderContext(plan_order, instrument_id, body)

    def order_parts(self):
        """Every order in this part, which is itself.

        Returns:
            list: This part.
        """
        return [
            self,
        ]

    def standalone_protecting_parts(self):
        """This part, when it protects a position on its own rather than one a Then join's first plan opened.

        Returns:
            list: This part when its side is `protect`, otherwise nothing.
        """
        if self.side == 'protect':
            return [
                self,
            ]
        return []

    def members(self):
        """The plans this part holds, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def needs_prices(self):
        """Whether this part reads quotes: for its trigger, its execution, its pricing or a modifier or guard, for a lifetime that ends on a price, or to make its order marketable when its lifetime ends.

        Returns:
            bool: True when it does.
        """
        if self.trigger is not None and self.trigger.needs_prices():
            return True
        if self.execution.needs_prices():
            return True
        if self.post_only is not None or self.discretion is not None:
            return True
        if self.lifetime is not None and self.lifetime.on_end == 'marketable':
            return True
        if self.lifetime is not None and self.lifetime.when is not None and self.lifetime.when.needs_prices():
            return True
        return self.pricing.needs_prices()

    def instruments(self):
        """The instruments other than the order's own that this part watches.

        Returns:
            list: The instrument ids.
        """
        watched = []
        if self.trigger is not None:
            watched = list(self.trigger.instruments())
        if self.lifetime is not None and self.lifetime.when is not None:
            for instrument_id in self.lifetime.when.instruments():
                if instrument_id not in watched:
                    watched.append(instrument_id)
        own = self.overrides.get('instrument_id')
        if own is not None and own not in watched:
            watched.append(own)
        if isinstance(self.pricing, FollowInstrumentPricing) and self.pricing.instrument_id not in watched:
            watched.append(self.pricing.instrument_id)
        return watched

    def moves_on_ticks(self):
        """Whether this part's resting orders are looked at on every tick, for a pricing that moves or for discretion.

        Returns:
            bool: True when they are.
        """
        return self.pricing.moves() or self.discretion is not None

    def prepared_pricing_memory(self, plan_order):
        """The pricing's first memory, readied when the plan is placed, such as an option's strike and expiry.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: The memory, empty for a pricing that needs nothing readied.

        Raises:
            RefusedRequestError: When the pricing cannot work for this order.
        """
        if isinstance(self.pricing, FollowInstrumentPricing):
            return self.pricing.prepared_memory(self.context(plan_order))
        return {}

    def prepared_own_memory(self, plan_order):
        """The memory a part kept whole readies when the plan is placed, which an ordinary order does not have.

        Args:
            plan_order (PlanOrder): Unused.

        Returns:
            dict: An empty dict.
        """
        del plan_order
        return {}

    def closes_position(self):
        """Whether this part's orders close a position, which is so for the `protect` and `close` sides.

        Returns:
            bool: True for `protect` and `close`.
        """
        return self.side in ('protect', 'close')

    def _opening_side(self, plan_order):
        """The side that opened the position this order works on: the side the first plan of its Then join filled on, or the body's side.

        Under a Then join the position is the one the first plan opened, which for a two-sided breakout is whichever side broke, so the side its filled broker orders traded is the one that counts. When both sides filled, the larger one is the position's side. Otherwise the body's side is read the way a validated order reads it: the API accepts the side in any case, so `buy` must be read as `BUY`. Comparing the raw value made a lower-case buy wait in the sell direction and fire at once, which a live test on 2026-10-01 caught.

        Args:
            plan_order (PlanOrder): The plan order, whose parent holds the body and the legs.

        Returns:
            str: BUY or SELL.
        """
        bought = 0
        sold = 0
        first_side = None
        for leg in plan_order.parent.legs:
            if leg.role in self.opened_by and (leg.filled_quantity or 0) > 0 and leg.transaction_type:
                side = str(leg.transaction_type).strip().upper()
                if first_side is None:
                    first_side = side
                if side == 'BUY':
                    bought = bought + leg.filled_quantity
                elif side == 'SELL':
                    sold = sold + leg.filled_quantity
        if bought > sold:
            return 'BUY'
        if sold > bought:
            return 'SELL'
        if first_side is not None:
            return first_side
        return str(self.context(plan_order).body.get('transaction_type') or '').strip().upper()

    def sending_side(self, opening_side, own_side=None):
        """The side this part's orders are sent on.

        Args:
            opening_side (str): BUY or SELL, the side that opened the position this part works on.
            own_side (str | None): BUY or SELL, the side of this part's own body, or None to take the opening side.

        Returns:
            str: BUY or SELL.
        """
        if self.side in ('protect', 'close'):
            return OPPOSITE_SIDES[opening_side]
        if self.side == 'same_as_first':
            return opening_side
        if self.side in NAMED_SIDES:
            return NAMED_SIDES[self.side]
        if own_side:
            return own_side
        return opening_side

    def _sending_side(self, plan_order):
        """The side this part's orders are sent on in this plan: against the position for `protect` and `close`, the named side for `buy` and `sell`, the first plan's filled side for `same_as_first`, against the option's delta for `against_delta` (opposite the opening side for a call, the same side for a put), and otherwise its own body's side.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            str: BUY or SELL.
        """
        if self.side == 'against_delta':
            opening_side = self._opening_side(plan_order)
            if self.fill_ratio.is_call(self.context(plan_order)):
                return OPPOSITE_SIDES[opening_side]
            return opening_side
        own_side = str(self.context(plan_order).body.get('transaction_type') or '').strip().upper()
        return self.sending_side(self._opening_side(plan_order), own_side)

    def prepare(self, plan_order, memory):
        """Readies the trigger when the plan is placed, such as working out when a time falls.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The part's memory, changed in place.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: When the trigger cannot be readied.
        """
        if self.trigger is None:
            return
        if 'trigger' not in memory:
            memory['trigger'] = {}
        self.trigger.prepare(self.context(plan_order), memory['trigger'])

    def refresh_held_terms(self, plan_order):
        """Rewrites the terms a `limit_marketable` trigger holds this order at, after a Using join has given it a rung's price and share.

        The trigger writes its terms when the plan is placed, before the join has divided the order into rungs, so without this every rung would be held at the whole order's price and quantity in the virtual order book's queue estimate.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        record = plan_order.part_record(self.path)
        memory = record.get('memory') or {}
        trigger_memory = memory.get('trigger') or {}
        terms = trigger_memory.get('held')
        if not isinstance(terms, dict):
            return
        body = self.context(plan_order).body
        terms = dict(terms)
        terms['price'] = str(body.get('price'))
        terms['quantity'] = body.get('quantity')
        trigger_memory = dict(trigger_memory)
        trigger_memory['held'] = terms
        memory = dict(memory)
        memory['trigger'] = trigger_memory
        record['memory'] = memory
        plan_order.set_part_record(self.path, record, None)

    def is_triggered(self, plan_order, memory, quotes, now):
        """Whether the trigger holds on this tick.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The part's memory, changed in place.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order should be placed now.
        """
        if self.trigger is None:
            return True
        if 'trigger' not in memory:
            memory['trigger'] = {}
        opening_side = self._opening_side(plan_order)
        return self.trigger.is_met(
            self.context(plan_order),
            memory['trigger'],
            quotes,
            now,
            opening_side,
            self._sending_side(plan_order),
        )

    def order(self, plan_order, quotes, quantity=None, price=None):
        """The order this part sends, priced now, or None when no price can be made yet or the post-only guard refused it.

        The quantity is the piece's when one is given; otherwise the target a parent join set, less what this part has already traded, or the body's quantity when no join set one. Only the plan's main order keeps the caller's tag, as today's exits do: the tag belongs to the order the caller asked for. The cap holds the priced limit, and the post-only guard then checks it against the book; a refusal ends this part as refused.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes to price from, by instrument id.
            quantity (int | None): The piece's quantity, or None for the whole order.
            price (decimal.Decimal | None): A limit price of the piece's own, such as a ladder rung's, which replaces the pricing's; None to price as usual.

        Returns:
            PlaceOrderRequest | None: The order.
        """
        context = self.context(plan_order)
        body = dict(context.body)
        sending_side = self._sending_side(plan_order)
        body['transaction_type'] = sending_side
        target = plan_order.part_record(self.path).get('target')
        if quantity is not None:
            body['quantity'] = quantity
            body.pop('quantity_reference', None)
        elif target is not None:
            body['quantity'] = target - self.traded(plan_order.parent)
            body.pop('quantity_reference', None)
        if not self.keeps_tag and 'tag' not in self.overrides:
            body.pop('tag', None)
        before = dict(body)
        record = plan_order.part_record(self.path)
        memory = copy.deepcopy(record.get('pricing_memory') or {})
        priced = self.pricing.priced_body(context, body, sending_side, quotes, memory)
        if priced is None:
            return None
        if memory != (record.get('pricing_memory') or {}):
            record['pricing_memory'] = memory
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part\'s pricing remembers {memory}')
        priced = self.with_caller_prices(priced, record)
        if self.cap is not None:
            priced = self.cap.capped_body(priced, sending_side)
        if self.post_only is not None:
            priced, refusal = self.post_only.checked_body(context.view(quotes), priced, sending_side)
            if refusal is not None:
                record = plan_order.part_record(self.path)
                record['state'] = 'done'
                record['reason'] = 'refused'
                record['message'] = refusal
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: {refusal}')
                return None
            if priced is None:
                return None
        if price is not None:
            priced['order_type'] = 'LIMIT'
            priced['price'] = str(price)
            priced.pop('trigger_price', None)
        if priced.get('price') != before.get('price'):
            priced.pop('price_reference', None)
        return plan_order.concrete_order(plan_order.read_order(priced))

    def with_caller_prices(self, priced, record):
        """The priced body with the price and trigger price a caller set before this part was sent, through `PUT /api/orders/modify` with `parent_id` and `part`.

        A market order given a price becomes a limit, and a stop-market becomes a stop-limit. A trigger price only replaces one the priced body already has, so a stop that the pricing sent as a limit because the market had gapped past it stays a limit.

        Args:
            priced (dict): The body as the pricing gave it, changed in place.
            record (dict): The part's record, which holds `caller_price` and `caller_trigger_price` once a caller has set them.

        Returns:
            dict: The body.
        """
        if record.get('caller_price') is not None:
            priced['price'] = record['caller_price']
            if priced.get('order_type') == 'MARKET':
                priced['order_type'] = 'LIMIT'
            if priced.get('order_type') == 'SL-M':
                priced['order_type'] = 'SL'
        if record.get('caller_trigger_price') is not None and priced.get('trigger_price') is not None:
            priced['trigger_price'] = record['caller_trigger_price']
        return priced

    def place(self, plan_order, started_at, quotes, quantity=None, price=None, broker_name=None):
        """Places this part's order, or one piece of it, or does nothing when no price can be made yet.

        Args:
            plan_order (PlanOrder): The plan order.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None.
            quotes (dict): The quotes to price from.
            quantity (int | None): The piece's quantity, or None for the whole order.
            price (decimal.Decimal | None): The piece's own limit price, or None.
            broker_name (str | None): The broker the execution chose for every piece, or None for the usual choice.

        Returns:
            tuple | None: The broker's answer (dict) and its HTTP status (int), or None when nothing was placed.
        """
        order = self.order(plan_order, quotes, quantity, price)
        if order is None:
            return None
        context = self.context(plan_order)
        if broker_name is None:
            broker_name = context.body.get('broker') or plan_order.chosen_broker()
        leg_group = None
        if broker_name is None:
            leg_group = plan_order.group_margin_legs
        body, status, _ = context.place_leg(
            self.path,
            order,
            started_at,
            broker_name,
            leg_group,
        )
        return body, status

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Starts this order: arms its trigger, or starts working and sends whatever its execution says is due now.

        A trigger that needs no prices and already holds, such as a `time_from` whose time has passed, sends the order at once rather than on the next tick.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): The quantity a parent join wants traded, or None for the body's.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.
            now (float | None): The Unix time now, or None to read the clock.

        Returns:
            list: One `(path, answer, status)` per broker order placed now.
        """
        record = plan_order.part_record(self.path)
        if record.get('ended'):
            record['state'] = 'done'
            record['reason'] = 'cancelled'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: cancelled by the caller before its turn came')
            return []
        if target is not None and self.fill_ratio is not None:
            target = self.fill_ratio.scaled(self.context(plan_order), target)
            if target is None:
                return []
            if target <= 0:
                record['target'] = target
                plan_order.set_part_record(self.path, record, None)
                return []
        if target is not None:
            record['target'] = target
        if target is not None and target <= 0:
            record['state'] = 'done'
            record['reason'] = 'cancelled'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part has nothing to trade')
            return []
        if self.trigger is not None:
            if now is None:
                now = time.time()
            memory = copy.deepcopy(record.get('memory') or {})
            holds_already = not self.trigger.needs_prices() and self.is_triggered(plan_order, memory, quotes, now)
            if not holds_already:
                record['state'] = 'waiting'
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is waiting for its trigger')
                return []
            record['fired_at'] = now
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is working')
        return self.send(plan_order, started_at, quotes, now)

    def send(self, plan_order, started_at, quotes, now=None):
        """Starts working now, when the order's trigger held or it was waiting for a price, and sends whatever is due.

        The execution's clock starts here, so a TWAP triggered at 10:30 spreads its slices from 10:30. When the first piece cannot be priced yet, an order sent all at once or by fills goes back to waiting and the next tick tries again, while an order paced by ticks starts working anyway, so its start is kept and later ticks send what falls due.

        Args:
            plan_order (PlanOrder): The plan order.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.
            now (float | None): The Unix time now, or None to read the clock.

        Returns:
            list: One `(path, answer, status)` per broker order placed.
        """
        if now is None:
            now = time.time()
        if self.position is not None:
            return self._close_positions(plan_order)
        record = plan_order.part_record(self.path)
        was_working = record.get('state') == 'working'
        if record.get('execution_memory') is None:
            memory = {}
            self.execution.begin(self.context(plan_order), memory, quotes, now)
            if memory:
                record['execution_memory'] = memory
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part started its execution')
        placed = self.send_due(plan_order, started_at, quotes, now)
        record = plan_order.part_record(self.path)
        if record.get('state') == 'done':
            return placed
        if not placed and not self.own_legs(plan_order.parent):
            if self.execution.paced_by_ticks() and record.get('state') != 'working':
                record['state'] = 'working'
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part started working, and nothing is due yet')
                return []
            if self.execution.paced_by_ticks():
                return []
            if record.get('state') != 'waiting':
                record['state'] = 'waiting'
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is waiting for a price')
            return []
        if record.get('state') == 'done' or was_working:
            return placed
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part\'s order was placed')
        return placed

    def _close_positions(self, plan_order):
        """Closes the positions a `close` order reads, and records what came of it.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per closing order placed.
        """
        placed, found, cancelled = self.position.close(plan_order, self.context(plan_order), self.path)
        record = plan_order.part_record(self.path)
        if found == 0:
            record['state'] = 'done'
            record['reason'] = 'nothing_held'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part cancelled {cancelled} resting orders and found nothing held to close')
            return placed
        if not placed:
            record['state'] = 'done'
            record['reason'] = 'refused'
            record['message'] = f'the book gave no price to close the {found} positions found'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: {record["message"]}')
            return placed
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part cancelled {cancelled} resting orders and sent {len(placed)} closing orders for {found} positions')
        return placed

    def total(self, plan_order):
        """How much this order should trade in all: the target a join set, or the body's quantity.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            int: The quantity.
        """
        record = plan_order.part_record(self.path)
        total = record.get('target')
        if total is None:
            total = self.context(plan_order).body.get('quantity') or 0
        return total + (record.get('caller_change') or 0)

    def committed(self, parent):
        """How much the broker orders sent so far account for: what filled of a finished one, and the whole of a resting one.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: The quantity.
        """
        total = 0
        for leg in self.own_legs(parent):
            if leg.is_finished():
                total = total + (leg.filled_quantity or 0)
            else:
                total = total + (leg.quantity or 0)
        return total

    def send_due(self, plan_order, started_at, quotes, now=None):
        """Sends the pieces this order's execution says are due now, each priced by the order's pricing.

        Every due piece is priced before any is sent, and when one cannot be priced none is sent, so the next tick asks again. Executions work out what they have sent from this order's broker orders, which recovery rebuilds after a restart, so nothing here has to be remembered between events.

        Args:
            plan_order (PlanOrder): The plan order.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.
            now (float | None): The Unix time now, or None to read the clock.

        Returns:
            list: One `(path, answer, status)` per broker order placed.
        """
        if now is None:
            now = time.time()
        record = plan_order.part_record(self.path)
        if record.get('ended'):
            return []
        stored = record.get('execution_memory') or {}
        memory = copy.deepcopy(stored)
        pieces = self.own_legs(plan_order.parent)
        sending_side = self._sending_side(plan_order)
        due = self.execution.due_pieces(self.context(plan_order), memory, self.total(plan_order), pieces, quotes, now, sending_side=sending_side)
        if not due:
            if memory != stored:
                record['execution_memory'] = memory
                plan_order.set_part_record(self.path, record, None)
            return []
        prices = [None] * len(due)
        if isinstance(self.execution, LadderExecution):
            prices = self.execution.rung_prices(self.context(plan_order), sending_side)
        for index, quantity in enumerate(due):
            if self.order(plan_order, quotes, quantity, prices[index]) is None:
                return []
        if memory != stored:
            record['execution_memory'] = memory
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part\'s execution moved on to {memory}')
        placed = []
        for index, quantity in enumerate(due):
            answer = self.place(plan_order, started_at, quotes, quantity, prices[index], memory.get('broker'))
            if answer is None:
                continue
            body, status = answer
            placed.append((self.path, body, status))
        if placed and len(due) == len(placed) and len(self.own_legs(plan_order.parent)) == len(placed):
            all_rejected = True
            for _, body, _ in placed:
                if body.get('outcome') != 'rejected':
                    all_rejected = False
            if all_rejected:
                record = plan_order.part_record(self.path)
                record['state'] = 'done'
                record['reason'] = 'refused'
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: refused')
        return placed

    def move(self, plan_order, quotes, now):
        """Moves this order's resting broker orders on a tick, for a pricing that moves, such as a peg or a trailing stop.

        Every resting order is asked about with the memory as it stood before the tick, so pieces resting side by side move together. The cap holds each new limit and the post-only guard checks it. The memory is recorded with an event when an order moved or the pricing started its clock, so a restart keeps it.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order was moved.
        """
        took = False
        if self.discretion is not None:
            took = self.discretion.take(self.context(plan_order), self, quotes)
        if not self.pricing.moves():
            return took
        resting = []
        for leg in self.own_legs(plan_order.parent):
            if not leg.is_finished() and leg.broker_order_id:
                resting.append(leg)
        if not resting:
            return False
        record = plan_order.part_record(self.path)
        stored = record.get('pricing_memory') or {}
        new_memory = stored
        moved_any = False
        reasons = []
        for leg in resting:
            memory = copy.deepcopy(stored)
            moved = self.pricing.moved_prices(self.context(plan_order), memory, leg, quotes, now)
            if memory != stored:
                new_memory = memory
            if moved is None:
                continue
            limit, trigger, reason = moved
            if self.cap is not None:
                limit = self.cap.capped(limit, leg.transaction_type)
            if self.post_only is not None:
                limit = self.post_only.checked_move(self.context(plan_order).view(quotes), limit, leg.transaction_type)
                if limit is None:
                    continue
            if plan_order.reprice_leg(leg, limit, trigger, reason):
                moved_any = True
                reasons.append(reason)
        if new_memory != stored:
            record = plan_order.part_record(self.path)
            record['pricing_memory'] = new_memory
            message = None
            if moved_any or not stored:
                message = f'the plan\'s {self.path} part\'s pricing remembers {new_memory}'
            plan_order.set_part_record(self.path, record, message)
        return moved_any or took

    def carry_on(self, plan_order, leg, before, quotes, now):
        """Lets this order's pricing carry on from a price or trigger the caller set on one of its broker orders, instead of moving it back.

        Only a pricing that moves keeps a copy of where the order should be, such as a trail's best price or a peg's offset, so only it has anything to bring in line. Its memory is recorded with an event, so a restart keeps the caller's values.

        Args:
            plan_order (PlanOrder): The plan order.
            leg (OrderLeg): The broker order the caller changed, holding its new values.
            before (dict): What the leg held before, with `quantity`, `price` and `trigger_price`.
            quotes (dict): The quotes now, by instrument id, empty when they could not be read.
            now (float): The Unix time of the change.

        Returns:
            None: This method returns nothing.
        """
        if not self.pricing.moves():
            return
        record = plan_order.part_record(self.path)
        memory = copy.deepcopy(record.get('pricing_memory') or {})
        message = self.pricing.carry_on(self.context(plan_order), memory, leg, before, quotes, now)
        if message is None:
            return
        record['pricing_memory'] = memory
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part: {message}')

    def keeps_caller_quantity(self):
        """Whether a caller's change to the quantity of one of this order's broker orders changes how much the order trades in all.

        An order sent all at once is that one broker order, so the caller's change is the new total. An execution that splits the order, such as an iceberg, sizes each later piece from what is still to trade, so the total stays what the plan asked for and the later pieces make up the difference, as today's iceberg and time-sliced types do.

        Returns:
            bool: True for an order sent all at once.
        """
        return isinstance(self.execution, AllAtOnceExecution)

    def take_caller_change(self, plan_order, change):
        """Counts a caller's change to this order's quantity, so a later fill or target cannot undo it.

        Args:
            plan_order (PlanOrder): The plan order.
            change (int): How much the caller added, negative for a cut.

        Returns:
            None: This method returns nothing.
        """
        record = plan_order.part_record(self.path)
        record['caller_change'] = (record.get('caller_change') or 0) + change
        plan_order.set_part_record(
            self.path,
            record,
            f'the caller changed the plan\'s {self.path} part by {change}, so it now trades {self.difference_described(record["caller_change"])} than the plan works out',
        )

    @staticmethod
    def difference_described(difference):
        """A caller's total change in words, such as `4 less` or `2 more`.

        Args:
            difference (int): The caller's total change, negative for a cut.

        Returns:
            str: The words.
        """
        if difference < 0:
            return f'{-difference} less'
        return f'{difference} more'

    def end_lifetime(self, plan_order, quotes, now):
        """Ends this order when its lifetime is up, or when its `when` condition holds: a waiting order is done, and a working one's resting orders are cancelled, made marketable, or cancelled and what filled closed.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried, for making resting orders marketable.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the lifetime ended on this tick.
        """
        if self.lifetime is None:
            return False
        record = plan_order.part_record(self.path)
        if record.get('ended'):
            return False
        state = record.get('state')
        if not self.lifetime.bounds(state):
            return False
        if self.lifetime.when is not None:
            memory = copy.deepcopy(record.get('lifetime_memory') or {})
            holds = self.lifetime.when.is_met(self.context(plan_order), memory, quotes, now, self._opening_side(plan_order), self._sending_side(plan_order))
            if memory != (record.get('lifetime_memory') or {}):
                record['lifetime_memory'] = memory
                plan_order.set_part_record(self.path, record, None)
            if not holds:
                return False
        else:
            ends_at = record.get('ends_at')
            if ends_at is None or now < ends_at:
                return False
        record['ended'] = True
        if state != 'working':
            record['state'] = 'done'
            record['reason'] = 'expired'
            if self.lifetime.when is not None:
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part ended before it was sent, because the condition that ends it held')
            else:
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part ran out of time before it was sent')
            return True
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part ran out of time, so it will {self.lifetime.on_end.replace("_", " ")}')
        if self.lifetime.on_end == 'marketable':
            self._make_marketable(plan_order, quotes)
            return True
        self.cancel_rest(plan_order, 'the time this order was given has run out')
        if self.lifetime.on_end == 'close_filled':
            self._close_filled(plan_order)
        return True

    def _make_marketable(self, plan_order, quotes):
        """Moves every resting order a little past the other side's touch, or the last price when the book shows no other side, so it fills.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.

        Returns:
            None: This method returns nothing.
        """
        view = self.context(plan_order).view(quotes)
        for leg in self.own_legs(plan_order.parent):
            if leg.is_finished() or not leg.broker_order_id:
                continue
            touch = view.opposite_touch(leg.transaction_type)
            if touch is None:
                touch = view.last()
            if touch is None:
                continue
            price = view.rounded(view.moved(touch, MARKETABLE_BUFFER_TICKS, leg.transaction_type, True), leg.transaction_type)
            if price is None or price <= 0:
                continue
            plan_order.reprice_leg(leg, price, None, 'the time this order was given has run out, so what is left is made marketable')

    def _close_filled(self, plan_order):
        """Closes what this order traded with a market order on the other side, placed under `<path>.close`, and marks the order done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        traded = self.traded(plan_order.parent)
        record = plan_order.part_record(self.path)
        record['state'] = 'done'
        if traded < 1:
            record['reason'] = 'expired'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part ran out of time before anything filled')
            return
        record['reason'] = 'closed'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part ran out of time, so the {traded} it traded is being closed')
        context = self.context(plan_order)
        body = dict(context.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('tag', None)
        body.pop('price', None)
        body.pop('trigger_price', None)
        body['order_type'] = 'MARKET'
        body['quantity'] = traded
        body['transaction_type'] = OPPOSITE_SIDES[self._sending_side(plan_order)]
        broker_name = plan_order.chosen_broker()
        context.place_leg(f'{self.path}.close', plan_order.concrete_order(plan_order.read_order(body)), None, broker_name)

    def settle(self, plan_order):
        """Sends the next piece when the execution waits for fills, and marks this order done once every broker order has finished and no more will be sent.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per broker order placed while settling.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working':
            return []
        placed = []
        if not self.execution.paced_by_ticks():
            placed = self.send_due(plan_order, None, plan_order.quotes_now() if self.needs_prices() else {})
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working':
            return placed
        remaining = self.total(plan_order) - self.committed(plan_order.parent)
        pieces = self.own_legs(plan_order.parent)
        if not record.get('ended') and self.execution.will_send_more(record.get('execution_memory') or {}, remaining, pieces):
            return placed
        reason = self.done_reason(plan_order.parent)
        if reason is None:
            return placed
        if self.waits_to_close_filled(record, reason):
            return placed
        record['state'] = 'done'
        record['reason'] = reason
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: {reason}')
        return placed

    def waits_to_close_filled(self, record, reason):
        """Whether this order stays working after its broker orders finished, because its lifetime will close what they filled.

        An order whose lifetime ends by closing what filled, such as a time stop's entry, must still be working when that time comes, or the lifetime, which only ends an order that is not done, would never close a position the entry filled completely. An order a caller cancelled, or whose lifetime has already ended, is marked `ended` and finishes as before.

        Args:
            record (dict): The order's part record.
            reason (str): Why its broker orders finished, from `done_reason`.

        Returns:
            bool: True when the order is left working for its lifetime to close.
        """
        if self.lifetime is None or self.lifetime.on_end != 'close_filled':
            return False
        if record.get('ended'):
            return False
        return reason in ('filled', 'partly_filled')

    def traded(self, parent):
        """How much this order's broker orders have filled.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: The quantity.
        """
        total = 0
        for leg in self.own_legs(parent):
            total = total + (leg.filled_quantity or 0)
        return total

    def set_target(self, plan_order, target):
        """Sets how much this order should trade in all, resizing or cancelling its resting order to match.

        A broker order's quantity is its total, filled part included, so a resting order is changed to what it has filled plus what is still wanted. When nothing more is wanted it is cancelled. An order the broker has not yet acknowledged is left alone, and the next settle tries again.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): The quantity.

        Returns:
            None: This method returns nothing.
        """
        if self.fill_ratio is not None:
            target = self.fill_ratio.scaled(self.context(plan_order), target)
            if target is None:
                return
        record = plan_order.part_record(self.path)
        state = record.get('state')
        if state == 'done':
            self._grow_finished(plan_order, record, target)
            return
        changed = record.get('target') != target
        record['target'] = target
        target = target + (record.get('caller_change') or 0)
        if state in ('pending', 'waiting'):
            if changed:
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part will trade {target}')
            if target <= 0:
                self.cancel_rest(plan_order, 'there is nothing left for it to trade')
            return
        if changed:
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part will trade {target}')
        if not self.execution.changes_its_order_to_grow():
            self._cut_resting_pieces(plan_order, target)
            return
        wanted = target - self.traded(plan_order.parent)
        resting = []
        for leg in self.own_legs(plan_order.parent):
            if not leg.is_finished() and leg.broker_order_id:
                resting.append(leg)
        for index, leg in enumerate(resting):
            if wanted <= 0:
                self.cancel_once(plan_order, leg, f'the plan\'s {self.path} part has nothing left to trade')
                continue
            unfilled = (leg.quantity or 0) - (leg.filled_quantity or 0)
            share = wanted
            if index < len(resting) - 1:
                share = min(wanted, unfilled)
            wanted = wanted - share
            new_total = (leg.filled_quantity or 0) + share
            if new_total != leg.quantity:
                plan_order.reduce_leg(
                    leg,
                    new_total,
                    f'the plan\'s {self.path} part should now trade {target} in all',
                )

    def _grow_finished(self, plan_order, record, target):
        """Sends a finished order again for what its target has grown by, so a later fill of the order it follows is covered.

        An exit that had already filled, or that its join cancelled when it had nothing left to trade, is done; when the entry it follows then fills further, the new quantity would otherwise have no exit. Such an order is reopened and sent a new broker order for the difference. Only an order that has sent a broker order before is reopened: one cancelled before it was ever sent, as the exits of an entry that never filled are, stays cancelled. An order a caller cancelled is `ended` and is not reopened, nor is one that was refused or expired, and neither is an order whose execution sends pieces rather than growing one order.

        Args:
            plan_order (PlanOrder): The plan order.
            record (dict): The order's part record.
            target (int): The quantity it should now trade in all, before the caller's change.

        Returns:
            None: This method returns nothing.
        """
        if record.get('ended') or record.get('reason') not in GROWN_AGAIN_REASONS:
            return
        if not self.execution.changes_its_order_to_grow() or not self.own_legs(plan_order.parent):
            return
        wanted = target + (record.get('caller_change') or 0) - self.traded(plan_order.parent)
        if wanted <= 0:
            return
        record['target'] = target
        record['state'] = 'working'
        record.pop('reason', None)
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part had finished, and is sent again for the {wanted} more it should now trade')
        quotes = {}
        if self.needs_prices():
            quotes = plan_order.quotes_now()
        self.place(plan_order, None, quotes, wanted)

    def _cut_resting_pieces(self, plan_order, target):
        """Brings the resting pieces down so they account for no more than `target`, newest first; a larger target is left to the execution, which sends more pieces.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): The quantity this order should trade in all.

        Returns:
            None: This method returns nothing.
        """
        excess = self.committed(plan_order.parent) - max(target, self.traded(plan_order.parent))
        legs = self.own_legs(plan_order.parent)
        legs.reverse()
        for leg in legs:
            if excess <= 0:
                return
            if leg.is_finished() or not leg.broker_order_id:
                continue
            filled = leg.filled_quantity or 0
            cut = min((leg.quantity or 0) - filled, excess)
            new_total = (leg.quantity or 0) - cut
            if new_total <= filled:
                self.cancel_once(plan_order, leg, f'the plan\'s {self.path} part should now trade {target} in all')
            else:
                plan_order.reduce_leg(leg, new_total, f'the plan\'s {self.path} part should now trade {target} in all')
            excess = excess - cut

    def cancel_rest(self, plan_order, reason):
        """Stops whatever of this order has not finished.

        An order that has not been placed is marked done as `cancelled`. A resting broker order is cancelled, and the order is marked done by the settle that follows the broker's confirmation.

        Args:
            plan_order (PlanOrder): The plan order.
            reason (str): Why, for the event log.

        Returns:
            bool: True when every resting broker order was cancelled, or none was resting.
        """
        record = plan_order.part_record(self.path)
        state = record.get('state')
        if state in ('pending', 'waiting'):
            record['state'] = 'done'
            record['reason'] = 'cancelled'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: cancelled, because {reason}')
            return True
        all_cancelled = True
        for leg in self.own_legs(plan_order.parent):
            if leg.is_finished() or not leg.broker_order_id:
                continue
            if not self.cancel_once(plan_order, leg, reason):
                all_cancelled = False
        return all_cancelled

    def cancel_for_caller(self, plan_order, reason):
        """Stops this order because a caller cancelled it: it sends nothing more, and whatever of it is resting is cancelled.

        An order whose turn has not come is marked `ended` and left where it is, so its join still starts its siblings as before, and `start` marks it done as `cancelled` without sending it; marking it done at once would tell the join that its branch had already started. A waiting order is marked done as `cancelled`. A working order is marked `ended`, as a lifetime that runs out marks it, so its execution sends no further piece and the next settle marks it done once the broker confirms the cancels.

        Args:
            plan_order (PlanOrder): The plan order.
            reason (str): Why, for the event log.

        Returns:
            bool: True when every resting broker order was cancelled, or none was resting.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') in (None, 'pending'):
            if not record.get('ended'):
                record['ended'] = True
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part will not be sent when its turn comes, because {reason}')
            return True
        if record.get('state') == 'working' and not record.get('ended'):
            record['ended'] = True
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part sends nothing more, because {reason}')
        return self.cancel_rest(plan_order, reason)

    def cancel_once(self, plan_order, leg, reason):
        """Asks the broker to cancel one of this part's orders, unless it has already accepted a cancel for it that is not confirmed yet.

        Every update settles the whole plan again, and a join that stops this part asks again on each one; without this, an order whose cancel is on its way is asked again, spending an order message each time. The leg ids whose cancel the broker accepted are kept in the part record as `cancel_asked`, without an event of their own, so after a restart at most one cancel is asked twice. A cancel the broker refused is not kept, so it is asked again.

        Args:
            plan_order (PlanOrder): The plan order.
            leg (OrderLeg): The broker order.
            reason (str): Why, for the event log.

        Returns:
            bool: True when the broker has accepted a cancel for it, now or before.
        """
        asked = plan_order.part_record(self.path).get('cancel_asked') or []
        if leg.leg_id in asked:
            return True
        if not plan_order.cancel_leg(leg, reason):
            return False
        record = plan_order.part_record(self.path)
        record['cancel_asked'] = list(record.get('cancel_asked') or []) + [
            leg.leg_id,
        ]
        plan_order.set_part_record(self.path, record, None)
        return True

    def is_started(self, plan_order):
        """Whether this order has been started.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True once it is waiting, working or done.
        """
        return plan_order.part_record(self.path).get('state') not in (None, 'pending')

    def is_done(self, plan_order):
        """Whether this order is done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True when it is.
        """
        return plan_order.part_record(self.path).get('state') == 'done'

    def own_legs(self, parent):
        """The broker orders this part placed.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            list: The legs whose role is this part's path.
        """
        found = []
        for leg in parent.legs:
            if leg.role == self.path:
                found.append(leg)
        return found

    def done_reason(self, parent):
        """Why this part is done, or None while it is not.

        It is done once every one of its broker orders has finished. The reason is `filled` when all of them filled, `partly_filled` when some quantity traded and the rest was cancelled, `refused` when a broker rejected it and nothing traded, and `cancelled` otherwise.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            str | None: The reason, or None when a broker order may still fill.
        """
        legs = self.own_legs(parent)
        if not legs:
            return None
        traded = 0
        all_filled = True
        any_rejected = False
        for leg in legs:
            if not leg.is_finished():
                return None
            traded = traded + (leg.filled_quantity or 0)
            if leg.state != 'filled':
                all_filled = False
            if leg.state == 'rejected':
                any_rejected = True
        if all_filled:
            return 'filled'
        if traded > 0:
            return 'partly_filled'
        if any_rejected:
            return 'refused'
        return 'cancelled'

    def quantity_described(self):
        """Where this part's quantity comes from, as a dry run shows it.

        Returns:
            str | int | dict: The position read when it fires, the order's own quantity, `the body's quantity` for the plan's main order, or `set by its join` for any other.
        """
        if self.position is not None:
            return self.position.described()
        if self.fill_ratio is not None:
            return self.fill_ratio.described()
        if 'quantity' in self.overrides:
            return self.overrides['quantity']
        if self.keeps_tag:
            return 'the body\'s quantity'
        return 'set by its join'

    def _pricing_described(self):
        """The pricing setter and its modifiers, as a dry run shows them.

        Returns:
            list: The setter, then the cap and the discretion when there are any.
        """
        described = [
            self.pricing.described(),
        ]
        if self.cap is not None:
            described.append(self.cap.described())
        if self.discretion is not None:
            described.append(self.discretion.described())
        return described

    def lifetime_ends_at(self, plan_order, now=None):
        """When this order's lifetime ends, worked out when the plan is placed.

        Args:
            plan_order (PlanOrder): The plan order.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            float | None: The Unix time, or None when the order has no lifetime of its own.

        Raises:
            RefusedRequestError: When the end cannot be worked out, such as a time already passed today.
        """
        if self.lifetime is None:
            return None
        return self.lifetime.ends_at(self.context(plan_order), now)

    def _guards_described(self):
        """The guards, as a dry run shows them.

        Returns:
            list: The post-only guard when there is one.
        """
        if self.post_only is None:
            return []
        return [
            self.post_only.described(),
        ]

    def _lifetime_described(self):
        """The lifetime, as a dry run shows it.

        Returns:
            list: The lifetime, or the body's validity when the order has none.
        """
        if self.lifetime is None:
            return [
                'the body\'s validity',
            ]
        return [
            self.lifetime.described(),
        ]

    def _venue_described(self):
        """The venue, as a dry run shows it.

        Returns:
            str | dict: `selector`, or the pre-open venue's settings.
        """
        if self.venue is None:
            return 'selector'
        return self.venue.described()

    def expanded(self):
        """This part as it will run, with every slot's value or default written out, for a dry run's answer.

        Returns:
            dict: The part's path, presets and slot values.
        """
        trigger = 'at_once'
        if self.trigger is not None:
            trigger = self.trigger.described()
        side = self.side or 'the body\'s transaction_type'
        return {
            'order': {
                'path': self.path,
                'presets': list(self.presets),
                'slots': {
                    'trigger': trigger,
                    'quantity': self.quantity_described(),
                    'side': side,
                    'execution': [
                        self.execution.described(),
                    ],
                    'pricing': self._pricing_described(),
                    'guards': self._guards_described(),
                    'venue': self._venue_described(),
                    'lifetime': self._lifetime_described(),
                },
            },
        }
