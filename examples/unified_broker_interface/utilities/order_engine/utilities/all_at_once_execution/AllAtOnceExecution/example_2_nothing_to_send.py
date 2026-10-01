"""Shows the default execution sending nothing for an order with nothing to trade, and nothing again after its order was cancelled.

`AllAtOnceExecution` sends at most once. An order whose join set it a target of zero has nothing to send, and an order whose one broker order was cancelled is not sent again, because whoever cancelled it meant it to stop. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/all_at_once_execution/AllAtOnceExecution/example_2_nothing_to_send.py
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


class NothingToSendExample:
    """Asks the execution about an empty order and a cancelled one."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = AllAtOnceExecution()
        plan_order = StandInPlanOrder()
        print(f'A target of zero: due {execution.due_pieces(plan_order, {}, 0, [], {}, 0.0)}')
        cancelled = [
            PieceMaker().piece(1, 10, 'cancelled', 3),
        ]
        print(f'Cancelled after 3 filled: due {execution.due_pieces(plan_order, {}, 10, cancelled, {}, 5.0)}, more to send {execution.will_send_more({}, 7, cancelled)}')


if __name__ == '__main__':
    NothingToSendExample().run()
