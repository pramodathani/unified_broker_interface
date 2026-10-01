"""One order in a plan: a leaf of the plan's tree, which places its own broker orders and says when it is done."""

import copy

OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}
NAMED_SIDES = {
    'buy': 'BUY',
    'sell': 'SELL',
}


class OrderPart:
    """One order in a plan, built afresh from the caller's plan on every event, with its state kept by the plan order.

    Every broker order it places carries its path as the leg's role, and it only ever looks at legs with that role, so another part's orders can never be mistaken for its own. That is the rule that lets parts be combined, where today's order types each assume they own every leg of the parent.

    An order with a trigger waits until the trigger holds and then places its order once. `side` is `buy` or `sell` to name the side, `protect` to trade against the position the caller's order opened, which sends the opposite side and counts as closing a position, or None for the body's own side. Pricing decides the order type and prices at the moment the order is sent.

    Attributes:
        path (str): Where the part sits in the plan, such as `root`.
        presets (list): The names of the presets it was built from, in order.
        trigger (object | None): The condition it waits for, or None to be placed at once.
        side (str | None): `buy`, `sell`, `protect`, or None for the body's side.
        pricing (object): The pricing that sets the order type and prices.
        keeps_tag (bool): Whether its orders carry the caller's tag, which only the plan's main order does.
    """

    def __init__(self, path, presets, trigger, side, pricing, keeps_tag=True):
        """Builds the part from values the plan reader has already checked.

        Args:
            path (str): Where the part sits in the plan.
            presets (list): The names of the presets it was built from, in order.
            trigger (object | None): The condition it waits for, or None.
            side (str | None): `buy`, `sell`, `protect`, or None.
            pricing (object): The pricing.
            keeps_tag (bool): Whether its orders carry the caller's tag.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.presets = presets
        self.trigger = trigger
        self.side = side
        self.pricing = pricing
        self.keeps_tag = keeps_tag

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
        """Whether this part reads quotes, for its trigger or its pricing.

        Returns:
            bool: True when it does.
        """
        if self.trigger is not None and self.trigger.needs_prices():
            return True
        return self.pricing.needs_prices()

    def instruments(self):
        """The instruments other than the order's own that this part watches.

        Returns:
            list: The instrument ids.
        """
        if self.trigger is None:
            return []
        return self.trigger.instruments()

    def closes_position(self):
        """Whether this part's orders close a position, which is so for the `protect` side.

        Returns:
            bool: True for `protect`.
        """
        return self.side == 'protect'

    def sending_side(self, opening_side):
        """The side this part's orders are sent on.

        Args:
            opening_side (str): BUY or SELL, the side of the caller's body.

        Returns:
            str: BUY or SELL.
        """
        if self.side == 'protect':
            return OPPOSITE_SIDES[opening_side]
        if self.side in NAMED_SIDES:
            return NAMED_SIDES[self.side]
        return opening_side

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
        self.trigger.prepare(plan_order, memory['trigger'])

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
        opening_side = plan_order.parent.body.get('transaction_type')
        return self.trigger.is_met(
            plan_order,
            memory['trigger'],
            quotes,
            now,
            opening_side,
            self.sending_side(opening_side),
        )

    def order(self, plan_order, quotes):
        """The order this part sends, priced now, or None when no price can be made yet.

        The quantity is the target a parent join set, less what this part has already traded, or the body's quantity when no join set one. Only the plan's main order keeps the caller's tag, as today's exits do: the tag belongs to the order the caller asked for.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes to price from, by instrument id.

        Returns:
            PlaceOrderRequest | None: The order.
        """
        body = dict(plan_order.parent.body)
        opening_side = body.get('transaction_type')
        sending_side = self.sending_side(opening_side)
        body['transaction_type'] = sending_side
        target = plan_order.part_record(self.path).get('target')
        if target is not None:
            body['quantity'] = target - self.traded(plan_order.parent)
            body.pop('quantity_reference', None)
        if not self.keeps_tag:
            body.pop('tag', None)
        before = dict(body)
        record = plan_order.part_record(self.path)
        memory = copy.deepcopy(record.get('pricing_memory') or {})
        priced = self.pricing.priced_body(plan_order, body, sending_side, quotes, memory)
        if priced is None:
            return None
        if memory != (record.get('pricing_memory') or {}):
            record['pricing_memory'] = memory
            plan_order.set_part_record(self.path, record, None)
        if priced.get('price') != before.get('price'):
            priced.pop('price_reference', None)
        return plan_order.concrete_order(plan_order.read_order(priced))

    def place(self, plan_order, started_at, quotes):
        """Places this part's order, or does nothing when no price can be made yet.

        Args:
            plan_order (PlanOrder): The plan order.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            tuple | None: The broker's answer (dict) and its HTTP status (int), or None when nothing was placed.
        """
        order = self.order(plan_order, quotes)
        if order is None:
            return None
        broker_name = plan_order.parent.body.get('broker') or plan_order.chosen_broker()
        body, status, _ = plan_order.place_leg(
            self.path,
            order,
            started_at,
            broker_name,
        )
        return body, status

    def start(self, plan_order, target, started_at, quotes):
        """Starts this order: arms its trigger, or places it at once.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): The quantity a parent join wants traded, or None for the body's.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` when an order was placed now, otherwise empty.
        """
        record = plan_order.part_record(self.path)
        if target is not None:
            record['target'] = target
        if target is not None and target <= 0:
            record['state'] = 'done'
            record['reason'] = 'cancelled'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part has nothing to trade')
            return []
        if self.trigger is not None:
            record['state'] = 'waiting'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is waiting for its trigger')
            return []
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is working')
        return self.send(plan_order, started_at, quotes)

    def send(self, plan_order, started_at, quotes):
        """Places this order now, or leaves it waiting for a tick when no price can be made yet.

        Args:
            plan_order (PlanOrder): The plan order.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` when an order was placed, otherwise empty.
        """
        placed = self.place(plan_order, started_at, quotes)
        record = plan_order.part_record(self.path)
        was_working = record.get('state') == 'working'
        if placed is None:
            record['state'] = 'waiting'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is waiting for a price')
            return []
        body, status = placed
        record['state'] = 'working'
        if body.get('outcome') == 'rejected':
            record['state'] = 'done'
            record['reason'] = 'refused'
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: refused')
        elif was_working:
            plan_order.set_part_record(self.path, record, None)
        else:
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part\'s order was placed')
        return [
            (self.path, body, status),
        ]

    def move(self, plan_order, quotes):
        """Moves this order's resting broker order on a tick, for a pricing that moves, such as a trailing stop.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.

        Returns:
            bool: True when the order was moved.
        """
        if not self.pricing.moves():
            return False
        resting = None
        for leg in self.own_legs(plan_order.parent):
            if not leg.is_finished() and leg.broker_order_id:
                resting = leg
        if resting is None:
            return False
        record = plan_order.part_record(self.path)
        memory = copy.deepcopy(record.get('pricing_memory') or {})
        moved = self.pricing.moved_prices(plan_order, memory, resting, quotes)
        if memory != (record.get('pricing_memory') or {}):
            record['pricing_memory'] = memory
            plan_order.set_part_record(self.path, record, None)
        if moved is None:
            return False
        limit, trigger, reason = moved
        return plan_order.reprice_leg(resting, limit, trigger, reason)

    def settle(self, plan_order):
        """Marks this order done once all of its broker orders have finished.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: Always empty, since settling an order places nothing.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working':
            return []
        reason = self.done_reason(plan_order.parent)
        if reason is None:
            return []
        record['state'] = 'done'
        record['reason'] = reason
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: {reason}')
        return []

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
        record = plan_order.part_record(self.path)
        state = record.get('state')
        if state == 'done':
            return
        changed = record.get('target') != target
        record['target'] = target
        if state in ('pending', 'waiting'):
            if changed:
                plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part will trade {target}')
            if target <= 0:
                self.cancel_rest(plan_order, 'there is nothing left for it to trade')
            return
        if changed:
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part will trade {target}')
        wanted = target - self.traded(plan_order.parent)
        for leg in self.own_legs(plan_order.parent):
            if leg.is_finished() or not leg.broker_order_id:
                continue
            if wanted <= 0:
                plan_order.cancel_leg(leg, f'the plan\'s {self.path} part has nothing left to trade')
                continue
            new_total = (leg.filled_quantity or 0) + wanted
            if new_total != leg.quantity:
                plan_order.reduce_leg(
                    leg,
                    new_total,
                    f'the plan\'s {self.path} part should now trade {target} in all',
                )

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
            if not plan_order.cancel_leg(leg, reason):
                all_cancelled = False
        return all_cancelled

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
            str: `the body's quantity` for the plan's main order, and `set by its join` for any other.
        """
        if self.keeps_tag:
            return 'the body\'s quantity'
        return 'set by its join'

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
                        'all_at_once',
                    ],
                    'pricing': [
                        self.pricing.described(),
                    ],
                    'guards': [],
                    'venue': 'selector',
                    'lifetime': [
                        'the body\'s validity',
                    ],
                },
            },
        }
