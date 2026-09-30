"""One order in a plan: a leaf of the plan's tree, which places its own broker orders and says when it is done."""

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
    """

    def __init__(self, path, presets, trigger, side, pricing):
        """Builds the part from values the plan reader has already checked.

        Args:
            path (str): Where the part sits in the plan.
            presets (list): The names of the presets it was built from, in order.
            trigger (object | None): The condition it waits for, or None.
            side (str | None): `buy`, `sell`, `protect`, or None.
            pricing (object): The pricing.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.presets = presets
        self.trigger = trigger
        self.side = side
        self.pricing = pricing

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
        before = dict(body)
        priced = self.pricing.priced_body(plan_order, body, sending_side, quotes)
        if priced is None:
            return None
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
                    'quantity': 'the body\'s quantity',
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
