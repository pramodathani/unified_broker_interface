"""One order in a plan: a leaf of the plan's tree, which places its own broker orders and says when it is done."""

DEFAULT_SLOTS = {
    'trigger': 'at_once',
    'quantity': 'the body\'s quantity',
    'side': 'the body\'s transaction_type',
    'execution': [
        'all_at_once',
    ],
    'pricing': [
        'fixed',
    ],
    'guards': [],
    'venue': 'selector',
    'lifetime': [
        'the body\'s validity',
    ],
}


class OrderPart:
    """One order in a plan, built afresh from the caller's plan on every event, with its state kept by the plan order.

    Every broker order it places carries its path as the leg's role, and it only ever looks at legs with that role, so another part's orders can never be mistaken for its own. That is the rule that lets parts be combined, where today's order types each assume they own every leg of the parent.

    Attributes:
        path (str): Where the part sits in the plan, such as `root`.
        presets (list): The names of the presets it was built from, in order.
    """

    def __init__(self, path, presets):
        """Builds the part.

        Args:
            path (str): Where the part sits in the plan.
            presets (list): The names of the presets it was built from, in order.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.presets = presets

    def start(self, plan_order, started_at):
        """Places this order's broker order.

        The order is the caller's body, with any price or quantity reference turned into a number, sent to the broker the body names or else to the one the selector chooses.

        Args:
            plan_order (PlanOrder): The plan order running this part.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None.

        Returns:
            tuple: The broker's answer (dict) and its HTTP status (int).
        """
        order = plan_order.concrete_order(
            plan_order.read_order(plan_order.parent.body),
        )
        body, status, _ = plan_order.place_leg(
            self.path,
            order,
            started_at,
            plan_order.parent.body.get('broker'),
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
        """This part as it will run, with every slot's default written out, for a dry run's answer.

        Returns:
            dict: The part's path, presets and slot values.
        """
        slots = {}
        for slot, value in DEFAULT_SLOTS.items():
            if isinstance(value, list):
                slots[slot] = list(value)
            else:
                slots[slot] = value
        return {
            'order': {
                'path': self.path,
                'presets': list(self.presets),
                'slots': slots,
            },
        }
