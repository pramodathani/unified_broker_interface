"""Compares how three urgencies share ten across three slices.

`FrontLoadedExecution` makes each slice `1 - urgency × 0.5` of the one before. An urgency of 0 is an even split, 0.5 shrinks each slice by a quarter, and 1 halves each, putting most of the order in the first slice. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/front_loaded_execution/FrontLoadedExecution/example_1_urgency_moves_the_order_early.py
"""

from unified_broker_interface.utilities.order_engine.utilities.front_loaded_execution import (
    FrontLoadedExecution,
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


class UrgencyMovesTheOrderEarlyExample:
    """Prints the weights and quantities for three urgencies."""

    def run(self):
        """Prints each urgency.

        Returns:
            None: This method returns nothing.
        """
        for urgency in (0.0, 0.5, 1.0):
            execution = FrontLoadedExecution(3, 3, urgency)
            print(f'urgency {urgency}: weights {execution.slice_weights({})}, ten as {execution.slice_quantities(10, {})}')
        print(f"As a dry run shows it: {FrontLoadedExecution(3, 3, 1.0).described()}")


if __name__ == '__main__':
    UrgencyMovesTheOrderEarlyExample().run()
