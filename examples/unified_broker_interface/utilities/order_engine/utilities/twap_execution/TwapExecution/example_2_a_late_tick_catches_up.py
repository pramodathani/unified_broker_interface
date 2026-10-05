"""Shows a TWAP sending at most one slice per tick, so a tick that arrives late sends the slice that is due and the next catches up.

`TwapExecution` keeps today's rule that one tick sends one slice. Here the ticks stop for a minute and a half; the next tick sends the second slice, and the slices after it follow on the ticks after that. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/twap_execution/TwapExecution/example_2_a_late_tick_catches_up.py
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


class ALateTickCatchesUpExample:
    """Walks a TWAP whose ticks pause."""

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
        pieces = []
        for seconds in (0, 100, 101, 102, 103):
            due = execution.due_pieces(plan_order, memory, 10, pieces, {}, float(seconds))
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'{seconds} s: due {due}, more to send {execution.will_send_more(memory, 10 - sum(piece.quantity for piece in pieces), pieces)}')


if __name__ == '__main__':
    ALateTickCatchesUpExample().run()
