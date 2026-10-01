"""The Sequence join: several plans run one after another, each starting once the one before is done."""


class SequencePart:
    """A branch of a plan whose children run one at a time, in order, each starting only when the one before it is done, whether it filled or ended.

    Closing shorts before longs is a Sequence of two closes; a stop and reverse that closes first and then opens the other side is another. Each child trades its own quantity.

    Attributes:
        path (str): Where the join sits in the plan.
        children (list): The plans, in the order they run.
    """

    def __init__(self, path, children):
        """Builds the join from parts the plan reader has already checked.

        Args:
            path (str): Where the join sits in the plan.
            children (list): The plans, in the order they run.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.children = children

    def order_parts(self):
        """Every order in this branch, in the children's order.

        Returns:
            list: The order parts.
        """
        found = []
        for child in self.children:
            found = found + child.order_parts()
        return found

    def standalone_protecting_parts(self):
        """The orders in this branch that protect a position they did not open themselves.

        Returns:
            list: The order parts.
        """
        found = []
        for child in self.children:
            found = found + child.standalone_protecting_parts()
        return found

    def members(self):
        """The plans this join holds directly.

        Returns:
            list: The children.
        """
        return list(self.children)

    def start(self, plan_order, target, started_at, quotes):
        """Starts the first child.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused, since each child trades its own quantity.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per order placed now.
        """
        del target
        return self.children[0].start(plan_order, None, started_at, quotes)

    def settle(self, plan_order):
        """Settles the children that have started, and starts the next one once the one before it is done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per order placed while settling.
        """
        placed = []
        for child in self.children:
            if not child.is_started(plan_order) and not child.is_done(plan_order):
                placed = placed + child.start(plan_order, None, None, plan_order.quotes_now())
            placed = placed + child.settle(plan_order)
            if not child.is_done(plan_order):
                break
        return placed

    def traded(self, parent):
        """How much the children traded between them.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: The quantity.
        """
        total = 0
        for child in self.children:
            total = total + child.traded(parent)
        return total

    def set_target(self, plan_order, target):
        """Does nothing, since each child trades its own quantity.

        Args:
            plan_order (PlanOrder): Unused.
            target (int): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, target

    def cancel_rest(self, plan_order, reason):
        """Stops every child, including those not started yet.

        Args:
            plan_order (PlanOrder): The plan order.
            reason (str): Why, for the event log.

        Returns:
            bool: True when every resting order was cancelled, or none was resting.
        """
        all_cancelled = True
        for child in self.children:
            if child.is_done(plan_order):
                continue
            if not child.cancel_rest(plan_order, reason):
                all_cancelled = False
        return all_cancelled

    def is_started(self, plan_order):
        """Whether the first child has started.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True once it has.
        """
        return self.children[0].is_started(plan_order)

    def is_done(self, plan_order):
        """Whether every child is done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True when they all are.
        """
        for child in self.children:
            if not child.is_done(plan_order):
                return False
        return True

    def expanded(self):
        """This join as it will run, for a dry run's answer.

        Returns:
            dict: The join and its children.
        """
        children = []
        for child in self.children:
            children.append(child.expanded())
        return {
            'sequence': {
                'path': self.path,
                'children': children,
            },
        }
