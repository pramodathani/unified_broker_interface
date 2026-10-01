"""The Then join: a first plan, and a child started from what the first one filled."""


class ThenPart:
    """A branch of a plan whose child is started from the first plan's fills and grows with them.

    With `each_fill`, the child starts on the first partial fill, sized to what has filled, and every later fill resizes it to the new total. That is how a bracket's exits follow its entry. With `on_complete`, the child waits until the first plan is done, and is sized to everything it filled. With `cancel_first_on_child_fill`, a fill on the child cancels whatever of the first plan is still working, which is a bracket's rule that an exit filling ends the entry.

    It works by settling: every event asks it to bring the child in line with the first plan's fills as they are now, rather than to add up changes, so a repeated or late update cannot count a fill twice.

    Attributes:
        path (str): Where the join sits in the plan.
        first (object): The first plan.
        child (object): The plan started from its fills.
        child_key (str): `each_fill` or `on_complete`.
        cancel_first_on_child_fill (bool): Whether a fill on the child cancels the rest of the first plan.
    """

    def __init__(self, path, first, child, child_key, cancel_first_on_child_fill):
        """Builds the join from parts the plan reader has already checked.

        Args:
            path (str): Where the join sits in the plan.
            first (object): The first plan.
            child (object): The child plan.
            child_key (str): `each_fill` or `on_complete`.
            cancel_first_on_child_fill (bool): Whether a fill on the child cancels the rest of the first plan.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.first = first
        self.child = child
        self.child_key = child_key
        self.cancel_first_on_child_fill = cancel_first_on_child_fill

    def order_parts(self):
        """Every order in this branch, first plan first.

        Returns:
            list: The order parts.
        """
        return self.first.order_parts() + self.child.order_parts()

    def standalone_protecting_parts(self):
        """The orders in this branch that protect a position they did not open themselves.

        The child's orders protect what the first plan filled, so only the first plan's are standalone.

        Returns:
            list: The order parts.
        """
        return self.first.standalone_protecting_parts()

    def members(self):
        """The plans this join holds directly.

        Returns:
            list: The first plan and the child.
        """
        return [
            self.first,
            self.child,
        ]

    def start(self, plan_order, target, started_at, quotes):
        """Starts the first plan; the child waits for its fills.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): The quantity the first plan should trade, or None for the body's.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per order placed now.
        """
        return self.first.start(plan_order, target, started_at, quotes)

    def settle(self, plan_order):
        """Brings the child in line with what the first plan has filled.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per order placed while settling.
        """
        placed = self.first.settle(plan_order)
        filled = self.first.traded(plan_order.parent)
        child_started = self.child.is_started(plan_order)
        if self.child_key == 'each_fill':
            may_start = filled > 0
        else:
            may_start = filled > 0 and self.first.is_done(plan_order)
        if may_start and not child_started:
            placed = placed + self.child.start(
                plan_order,
                filled,
                None,
                plan_order.quotes_now(),
            )
        elif child_started:
            self.child.set_target(plan_order, filled)
        if self.first.is_done(plan_order) and filled == 0 and not child_started:
            self.child.cancel_rest(
                plan_order,
                'the first plan finished without filling anything',
            )
        placed = placed + self.child.settle(plan_order)
        if self.cancel_first_on_child_fill and self.child.traded(plan_order.parent) > 0:
            self.first.cancel_rest(
                plan_order,
                'the child has started filling, so the rest of the first plan is stopped',
            )
        return placed

    def traded(self, parent):
        """How much the first plan traded, which is what this branch opened.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: The quantity.
        """
        return self.first.traded(parent)

    def set_target(self, plan_order, target):
        """Sets how much the first plan should trade.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): The quantity.

        Returns:
            None: This method returns nothing.
        """
        self.first.set_target(plan_order, target)

    def cancel_rest(self, plan_order, reason):
        """Stops everything in this branch that has not finished.

        Args:
            plan_order (PlanOrder): The plan order.
            reason (str): Why, for the event log.

        Returns:
            None: This method returns nothing.
        """
        self.first.cancel_rest(plan_order, reason)
        self.child.cancel_rest(plan_order, reason)

    def is_started(self, plan_order):
        """Whether the first plan has started.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True once it has.
        """
        return self.first.is_started(plan_order)

    def is_done(self, plan_order):
        """Whether both the first plan and the child are done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True when they are.
        """
        return self.first.is_done(plan_order) and self.child.is_done(plan_order)

    def expanded(self):
        """This join as it will run, for a dry run's answer.

        Returns:
            dict: The join, its settings and its plans.
        """
        return {
            'then': {
                'path': self.path,
                'first': self.first.expanded(),
                self.child_key: self.child.expanded(),
                'cancel_first_on_child_fill': self.cancel_first_on_child_fill,
            },
        }
