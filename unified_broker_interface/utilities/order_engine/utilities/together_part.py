"""The Together join: several plans run at once and independently, such as the legs of a basket."""

from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)

DONE_WHEN = (
    'all',
    'any',
)


class TogetherPart:
    """A branch of a plan whose children start at once and run independently, each with its own quantity, as a basket's legs do.

    Every broker order of one plan already goes to the broker the first one chose, so the children share a broker, which is what lets a hedged strategy's margin offsets apply. With `group_margin`, the first order to be placed hands every child's order to the broker selector, so the broker it picks can afford the whole group, priced as a hedged whole at the brokers known to allow it when `hedge_benefit` is set. With `done_when: any`, the join is done as soon as one child is, and the rest are cancelled; with `all`, the default, it is done when every child is.

    Attributes:
        path (str): Where the join sits in the plan.
        children (list): The plans that run at once.
        group_margin (bool): Whether the broker is chosen for the whole group's margin.
        hedge_benefit (bool): Whether the group's margin is priced as a hedged whole.
        done_when (str): `all` or `any`.
    """

    def __init__(self, path, children, group_margin, hedge_benefit, done_when):
        """Builds the join from parts the plan reader has already checked.

        Args:
            path (str): Where the join sits in the plan.
            children (list): The plans that run at once.
            group_margin (bool): Whether the broker is chosen for the whole group's margin.
            hedge_benefit (bool): Whether the group's margin is priced as a hedged whole.
            done_when (str): `all` or `any`.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.children = children
        self.group_margin = group_margin
        self.hedge_benefit = hedge_benefit
        self.done_when = done_when

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

    def group_legs(self, plan_order, quotes):
        """Every order the group sends at once, for the broker selector to check the margin of together.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes to price from.

        Returns:
            OrderLegs | None: The group, or None when an order cannot be priced yet.
        """
        legs = []
        for part in self.order_parts():
            if part.trigger is not None:
                continue
            order = part.order(plan_order, quotes)
            if order is None:
                return None
            legs.append((part.context(plan_order).instrument_id, order))
        if not legs:
            return None
        return OrderLegs(legs, self.hedge_benefit)

    def start(self, plan_order, target, started_at, quotes):
        """Starts every child with its own quantity, handing the group to the broker selector first when the margin is checked together.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused, since each child trades its own quantity.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per order placed now.
        """
        del target
        if self.group_margin and plan_order.chosen_broker() is None:
            plan_order.group_margin_legs = self.group_legs(plan_order, quotes)
        placed = []
        for child in self.children:
            placed = placed + child.start(plan_order, None, started_at, quotes)
        plan_order.group_margin_legs = None
        return placed

    def settle(self, plan_order):
        """Settles every child, and with `done_when: any` cancels the rest once one is done.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per order placed while settling.
        """
        placed = []
        for child in self.children:
            placed = placed + child.settle(plan_order)
        if self.done_when == 'any':
            for child in self.children:
                if child.is_done(plan_order):
                    self.cancel_rest(plan_order, f'{child.path} is done, and the group is done when any of its plans is')
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
        """Stops every child.

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
        """Whether every child is done, which with `done_when: any` follows once the first is and the rest are cancelled.

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
            'together': {
                'path': self.path,
                'group_margin': self.group_margin,
                'hedge_benefit': self.hedge_benefit,
                'done_when': self.done_when,
                'children': children,
            },
        }
