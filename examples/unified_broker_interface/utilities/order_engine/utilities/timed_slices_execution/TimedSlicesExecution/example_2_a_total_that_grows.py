"""Shows a timed execution whose total grows halfway through, and the base class refusing to guess its own weights.

`TimedSlicesExecution` works out each slice's size from the order's total when the slice falls due, so a total a join grows is spread over the slices still to come, and the last slice sends whatever is left. On its own the base class has no weights, so asking it for them raises `NotImplementedError`. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/timed_slices_execution/TimedSlicesExecution/example_2_a_total_that_grows.py
"""

from unified_broker_interface.utilities.order_engine.utilities.timed_slices_execution import (
    TimedSlicesExecution,
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


class EvenExecution(TimedSlicesExecution):
    """Slices of equal weight."""

    NAME = 'even'

    def slice_weights(self, memory):
        """Every slice the same.

        Args:
            memory (dict): Unused.

        Returns:
            list: One weight per slice.
        """
        del memory
        return [1.0] * self.slices


class ATotalThatGrowsExample:
    """Walks a four-slice schedule whose total grows from 8 to 20."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        try:
            TimedSlicesExecution(2, 1).slice_weights({})
        except NotImplementedError as error:
            print(f'The base class alone: {error}')
        execution = EvenExecution(4, 2)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        memory = {}
        execution.begin(plan_order, memory, {}, 0.0)
        pieces = []
        for seconds, total in ((0, 8), (30, 8), (60, 20), (90, 20)):
            due = execution.due_pieces(plan_order, memory, total, pieces, {}, float(seconds))
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'{seconds} s with a total of {total}: due {due}')
        print(f'Sent {[piece.quantity for piece in pieces]}, adding up to {sum(piece.quantity for piece in pieces)}')


if __name__ == '__main__':
    ATotalThatGrowsExample().run()
