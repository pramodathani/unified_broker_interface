"""Asks the default execution what to send, before and after its one order has gone.

`AllAtOnceExecution` sends an order's whole quantity as one broker order, which is what every plan order does unless it names another execution. Whether it has sent is read from the order's broker orders, which recovery rebuilds after a restart, so a restarted engine never sends it twice. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/all_at_once_execution/AllAtOnceExecution/example_1_sends_everything_once.py
"""

from unified_broker_interface.utilities.order_engine.utilities.all_at_once_execution import (
    AllAtOnceExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


class StandInParent:
    """Stands in for a plan order's parent, which only needs an id here.

    Attributes:
        parent_order_id (str): The parent's id.
    """

    def __init__(self):
        """Builds the parent.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = '0f5e2c1a-7b3d-4e9f-8a21-6c4d2b1e9f00'


class StandInPlanOrder:
    """Stands in for the plan order an execution is asked about.

    Attributes:
        parent (StandInParent): The parent.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()


class PieceMaker:
    """Builds broker orders as the engine records them, in a chosen state."""

    def piece(self, number, quantity, state, filled):
        """One broker order.

        Args:
            number (int): Its number, for its id.
            quantity (int): Its quantity.
            state (str): Its state, such as `acknowledged` or `filled`.
            filled (int): How much of it has filled.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg(f'parent-1:{number}', 'root')
        leg.quantity = quantity
        leg.state = state
        leg.filled_quantity = filled
        return leg


class SendsEverythingOnceExample:
    """Asks the execution about an order of ten, before and after it is sent."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = AllAtOnceExecution()
        plan_order = StandInPlanOrder()
        memory = {}
        execution.begin(plan_order, memory, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        print(f'Memory after beginning: {memory}')
        print(f'Due before anything is sent: {execution.due_pieces(plan_order, memory, 10, [], {}, 0.0)}; more to send: {execution.will_send_more(memory, 10, [])}')
        sent = [
            PieceMaker().piece(1, 10, 'acknowledged', 0),
        ]
        print(f'Due once it is resting: {execution.due_pieces(plan_order, memory, 10, sent, {}, 1.0)}; more to send: {execution.will_send_more(memory, 0, sent)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    SendsEverythingOnceExample().run()
