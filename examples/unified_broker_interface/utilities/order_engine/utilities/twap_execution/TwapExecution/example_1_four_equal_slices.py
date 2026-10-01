"""Sends ten as four TWAP slices over two minutes: 3, 3, 2 and 2, thirty seconds apart.

`TwapExecution` weights every slice the same, so the quantity is split as evenly as whole units allow, the left-over units going to the earliest slices. The first slice goes at once and each later one when its time comes. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/twap_execution/TwapExecution/example_1_four_equal_slices.py
"""

from unified_broker_interface.utilities.order_engine.utilities.twap_execution import (
    TwapExecution,
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


class FourEqualSlicesExample:
    """Walks a four-slice TWAP."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = TwapExecution(4, 2)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        memory = {}
        execution.begin(plan_order, memory, {}, 0.0)
        print(f'Weights {execution.slice_weights(memory)}, ten shared out as {execution.slice_quantities(10, memory)}')
        pieces = []
        for seconds in (0, 10, 30, 60, 90):
            due = execution.due_pieces(plan_order, memory, 10, pieces, {}, float(seconds))
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'{seconds} s: due {due}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    FourEqualSlicesExample().run()
