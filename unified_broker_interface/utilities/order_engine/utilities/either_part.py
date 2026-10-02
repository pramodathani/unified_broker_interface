"""The Either join: several plans running at once, where a fill on one changes the others."""

from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)

SIBLING_RULES = (
    'cancel',
    'reduce',
)


class EitherPart:
    """A branch of a plan whose children run at once, and whose `sibling_rule` says what a fill on one does to the rest.

    `cancel` suits children that are different trades, such as the two sides of a breakout: once any child has filled something, every other child is cancelled, including children still waiting on a trigger. `reduce` suits exits on one position, such as a stop and a target: the children share one quantity, and each is kept at that quantity less what its siblings have filled, so a partial fill on the target shrinks the stop by exactly that much and no more. Keeping each child at a total worked out from the fills as they are now, rather than taking changes off, is what stops a second partial fill being counted twice.

    With `cancel_before_send`, a child whose trigger holds first cancels its siblings' resting orders and is sent only once every cancel has been accepted, so a hidden stop and its native backstop cannot both fill.

    Attributes:
        path (str): Where the join sits in the plan.
        children (list): The plans that run at once.
        sibling_rule (str): One of `SIBLING_RULES`.
        cancel_before_send (bool): Whether a child cancels its siblings before it is sent.
    """

    def __init__(self, path, children, sibling_rule, cancel_before_send):
        """Builds the join from parts the plan reader has already checked.

        Args:
            path (str): Where the join sits in the plan.
            children (list): The plans that run at once.
            sibling_rule (str): One of `SIBLING_RULES`.
            cancel_before_send (bool): Whether a child cancels its siblings before it is sent.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.children = children
        self.sibling_rule = sibling_rule
        self.cancel_before_send = cancel_before_send

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

    def budget(self, plan_order):
        """The quantity the children share: what a parent join set, or the body's quantity.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            int: The quantity.
        """
        record = plan_order.part_record(self.path)
        budget = record.get('target')
        if budget is None:
            budget = plan_order.parent.body.get('quantity') or 0
        return budget + (record.get('caller_change') or 0)

    def take_caller_change(self, plan_order, change):
        """Counts a caller's change to one child's quantity against the quantity every child shares, so the other exits follow it and no later fill undoes it.

        Under the `reduce` rule the children are exits on one position. Cutting one and not the others would leave them covering different amounts, so the cut comes off the shared quantity, as today's linked pair of exits brings the other exit down to the quantity the caller set.

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
            f'the caller changed one of the plan\'s {self.path} children by {change}, so every child shares {OrderPart.difference_described(record["caller_change"])} than the plan works out',
        )

    def start(self, plan_order, target, started_at, quotes):
        """Starts every child, each with the shared quantity.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): The shared quantity, or None for the body's.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per order placed now.
        """
        if target is not None:
            record = plan_order.part_record(self.path)
            record['target'] = target
            plan_order.set_part_record(self.path, record, None)
        placed = []
        for child in self.children:
            placed = placed + child.start(plan_order, target, started_at, quotes)
        return placed

    def settle(self, plan_order):
        """Brings every child in line with what its siblings have filled.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per order placed while settling, which is none.
        """
        placed = []
        for child in self.children:
            placed = placed + child.settle(plan_order)
        fills = []
        for child in self.children:
            fills.append(child.traded(plan_order.parent))
        if self.sibling_rule == 'reduce':
            budget = self.budget(plan_order)
            total = sum(fills)
            for index, child in enumerate(self.children):
                if not child.is_started(plan_order) and child.is_done(plan_order):
                    continue
                siblings_filled = total - fills[index]
                child.set_target(plan_order, budget - siblings_filled)
        else:
            for index, child in enumerate(self.children):
                if fills[index] > 0:
                    self.cancel_siblings(
                        plan_order,
                        index,
                        f'{child.path} has started filling, so its siblings are cancelled',
                    )
                    break
        for child in self.children:
            placed = placed + child.settle(plan_order)
        return placed

    def cancel_siblings(self, plan_order, index, reason):
        """Stops every child but one.

        Args:
            plan_order (PlanOrder): The plan order.
            index (int): The position of the child to keep.
            reason (str): Why, for the event log.

        Returns:
            bool: True when every resting order of the other children was cancelled, or none was resting.
        """
        all_cancelled = True
        for other_index, other in enumerate(self.children):
            if other_index == index:
                continue
            if not other.cancel_rest(plan_order, reason):
                all_cancelled = False
        return all_cancelled

    def child_index(self, path):
        """The position of the child whose branch holds a path.

        Args:
            path (str): A part's path.

        Returns:
            int | None: The position, or None when no child holds it.
        """
        for index, child in enumerate(self.children):
            if path == child.path or path.startswith(f'{child.path}.'):
                return index
        return None

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
        """Sets the quantity the children share; the next settle applies it.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): The quantity.

        Returns:
            None: This method returns nothing.
        """
        record = plan_order.part_record(self.path)
        if record.get('target') == target:
            return
        record['target'] = target
        plan_order.set_part_record(
            self.path,
            record,
            f'the plan\'s {self.path} children now share {target}',
        )

    def cancel_rest(self, plan_order, reason):
        """Stops every child.

        Args:
            plan_order (PlanOrder): The plan order.
            reason (str): Why, for the event log.

        Returns:
            bool: True when every resting order was cancelled, or none was resting.
        """
        all_cancelled = True
        for child in self.children:
            if not child.cancel_rest(plan_order, reason):
                all_cancelled = False
        return all_cancelled

    def is_started(self, plan_order):
        """Whether any child has started.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True once one has.
        """
        for child in self.children:
            if child.is_started(plan_order):
                return True
        return False

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
            dict: The join, its settings and its children.
        """
        children = []
        for child in self.children:
            children.append(child.expanded())
        return {
            'either': {
                'path': self.path,
                'sibling_rule': self.sibling_rule,
                'cancel_before_send': self.cancel_before_send,
                'children': children,
            },
        }
