"""Starts a group of three orders on three instruments, with the broker chosen for the whole group's margin.

`TogetherPart.start` builds the group with `group_legs` and hands it to the plan order as `group_margin_legs` while the orders start, so the broker selector, which only chooses for the first order, checks that one broker can afford all three; it then clears it. Each child trades its own quantity, so `set_target` does nothing. Stand-in orders record what they are asked, and nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/together_part/TogetherPart/example_1_a_basket_at_one_broker.py
"""

from unified_broker_interface.utilities.order_engine.utilities.together_part import (
    TogetherPart,
)


class StandInPlanOrder:
    """Stands in for the plan order, keeping the parts' states and the group a Together join hands the broker selector.

    Attributes:
        states (dict): Each part's state by path.
        group_margin_legs (OrderLegs | None): The group the selector would check, while orders go out.
        broker (str | None): The broker the plan's orders went to, or None before any did.
        log (list): What happened, in order.
    """

    def __init__(self):
        """Builds the stand-in with nothing started.

        Returns:
            None: This method returns nothing.
        """
        self.states = {}
        self.group_margin_legs = None
        self.broker = None
        self.log = []

    def chosen_broker(self):
        """The broker the plan's orders went to.

        Returns:
            str | None: The broker, or None before any order went.
        """
        return self.broker

    def quotes_now(self):
        """The quotes now, which are none here.

        Returns:
            dict: An empty dictionary.
        """
        return {}


class StandInContext:
    """Stands in for an order's view of the plan order, naming its instrument.

    Attributes:
        instrument_id (str): The instrument.
    """

    def __init__(self, instrument_id):
        """Builds the context.

        Args:
            instrument_id (str): The instrument.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id


class StandInOrder:
    """Stands in for one order of a plan, which records what it is asked to do.

    Attributes:
        path (str): Its path.
        instrument_id (str): The instrument it trades.
        trigger (object | None): Its trigger, always None here.
    """

    def __init__(self, path, instrument_id):
        """Builds the order.

        Args:
            path (str): Its path.
            instrument_id (str): The instrument it trades.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.instrument_id = instrument_id
        self.trigger = None

    def order_parts(self):
        """The orders in this part, which is itself.

        Returns:
            list: This order.
        """
        return [
            self,
        ]

    def standalone_protecting_parts(self):
        """The orders protecting a position on their own, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def context(self, plan_order):
        """The order's view of the plan order.

        Args:
            plan_order (StandInPlanOrder): Unused.

        Returns:
            StandInContext: The context.
        """
        del plan_order
        return StandInContext(self.instrument_id)

    def order(self, plan_order, quotes):
        """The order it would send, as a short description.

        Args:
            plan_order (StandInPlanOrder): Unused.
            quotes (dict): Unused.

        Returns:
            str: The description.
        """
        del plan_order, quotes
        return f'an order on {self.instrument_id}'

    def start(self, plan_order, target, started_at, quotes):
        """Starts the order, noting whether the selector was handed a group.

        Args:
            plan_order (StandInPlanOrder): The plan order.
            target (int | None): Unused.
            started_at (float | None): Unused.
            quotes (dict): Unused.

        Returns:
            list: One placement.
        """
        del target, started_at, quotes
        group = plan_order.group_margin_legs
        handed = None if group is None else group.instrument_ids()
        plan_order.log.append(f'{self.path} starts, the selector holding {handed}')
        plan_order.states[self.path] = 'working'
        plan_order.broker = 'zerodha'
        return [
            (self.path, {'outcome': 'accepted'}, 200),
        ]

    def settle(self, plan_order):
        """Settles nothing.

        Args:
            plan_order (StandInPlanOrder): Unused.

        Returns:
            list: An empty list.
        """
        del plan_order
        return []

    def traded(self, parent):
        """How much it traded, which is none here.

        Args:
            parent (object): Unused.

        Returns:
            int: Zero.
        """
        del parent
        return 0

    def cancel_rest(self, plan_order, reason):
        """Marks the order done as cancelled.

        Args:
            plan_order (StandInPlanOrder): The plan order.
            reason (str): Why.

        Returns:
            bool: True.
        """
        plan_order.log.append(f'{self.path} cancelled: {reason}')
        plan_order.states[self.path] = 'done'
        return True

    def is_started(self, plan_order):
        """Whether it has started.

        Args:
            plan_order (StandInPlanOrder): The plan order.

        Returns:
            bool: True once it has.
        """
        return self.path in plan_order.states

    def is_done(self, plan_order):
        """Whether it is done.

        Args:
            plan_order (StandInPlanOrder): The plan order.

        Returns:
            bool: True when it is.
        """
        return plan_order.states.get(self.path) == 'done'

    def expanded(self):
        """The order as a dry run shows it.

        Returns:
            dict: Its path and instrument.
        """
        return {
            'order': {
                'path': self.path,
                'instrument_id': self.instrument_id,
            },
        }


class ABasketAtOneBrokerExample:
    """Starts a basket and prints what happened."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        children = [
            StandInOrder('root.children.0', 'RELIANCE'),
            StandInOrder('root.children.1', 'KWIL'),
            StandInOrder('root.children.2', 'NIFTY 25000 CE'),
        ]
        join = TogetherPart('root', children, True, True, 'all')
        plan_order = StandInPlanOrder()
        print(f'Orders: {[part.path for part in join.order_parts()]}, members: {len(join.members())}, protecting on their own: {join.standalone_protecting_parts()}')
        placed = join.start(plan_order, None, None, {})
        for line in plan_order.log:
            print(line)
        print(f'Placed {len(placed)}; the selector holds nothing afterwards: {plan_order.group_margin_legs}')
        join.set_target(plan_order, 4)
        print(f'Started: {join.is_started(plan_order)}, done: {join.is_done(plan_order)}, traded: {join.traded(None)}, settle placed {join.settle(plan_order)}')
        print(f'As a dry run shows it: {join.expanded()}')


if __name__ == '__main__':
    ABasketAtOneBrokerExample().run()
