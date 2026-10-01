"""Shows the schedule every timed execution shares, through a small subclass that weights its slices one to three.

`TimedSlicesExecution` cuts an order into `slices`, one every `over_minutes × 60 / slices` seconds with the first at once, and shares the quantity out by weight with the largest-remainder method. A subclass says only how the slices are weighted; this program's subclass weights them 1, 2 and 3 so the sharing is easy to follow. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/timed_slices_execution/TimedSlicesExecution/example_1_the_shared_schedule.py
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


class OneTwoThreeExecution(TimedSlicesExecution):
    """Three slices weighted one, two and three."""

    NAME = 'one_two_three'

    def slice_weights(self, memory):
        """The weights 1, 2 and 3.

        Args:
            memory (dict): Unused.

        Returns:
            list: The weights.
        """
        del memory
        return [
            1.0,
            2.0,
            3.0,
        ]


class TheSharedScheduleExample:
    """Walks a three-slice schedule over three minutes."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = OneTwoThreeExecution(3, 3)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        memory = {}
        execution.begin(plan_order, memory, {}, 1000.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        print(f'Interval {execution.interval()} s, memory {memory}, weights {execution.slice_weights(memory)}, 100 shared out as {execution.slice_quantities(100, memory)}')
        pieces = []
        for seconds in (0, 30, 60, 90, 120, 180):
            due = execution.due_pieces(plan_order, memory, 100, pieces, {}, 1000.0 + seconds)
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'{seconds} s: due {due}, more to send {execution.will_send_more(memory, 100 - sum(piece.quantity for piece in pieces), pieces)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    TheSharedScheduleExample().run()
