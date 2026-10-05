"""Sends a front-loaded order of ten over three minutes: six at once, then three, then one.

`FrontLoadedExecution` keeps the shared timed schedule, a slice every minute here with the first at once, and only weights the slices differently. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/front_loaded_execution/FrontLoadedExecution/example_2_sent_on_the_clock.py
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

    def lot_size(self):
        """The lot every slice must be a whole number of, which for a share is one.

        Returns:
            int: One.
        """
        return 1


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


class SentOnTheClockExample:
    """Walks a three-slice front-loaded order with an urgency of 1."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = FrontLoadedExecution(3, 3, 1.0)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        memory = {}
        execution.begin(plan_order, memory, {}, 0.0)
        pieces = []
        for seconds in (0, 60, 120):
            due = execution.due_pieces(plan_order, memory, 10, pieces, {}, float(seconds))
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'{seconds} s: due {due}')


if __name__ == '__main__':
    SentOnTheClockExample().run()
