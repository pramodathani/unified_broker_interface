"""Walks an iceberg of ten, showing four at a time, through its pieces filling one after another.

`IcebergExecution` sends the next piece only once nothing is resting and the last piece filled, and the last piece takes whatever is left. `committed` is how much the pieces sent so far account for: what filled of a finished piece and the whole of a resting one. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/iceberg_execution/IcebergExecution/example_1_one_piece_at_a_time.py
"""

from unified_broker_interface.utilities.order_engine.utilities.iceberg_execution import (
    IcebergExecution,
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


class OnePieceAtATimeExample:
    """Asks an iceberg what to send as its pieces fill."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = IcebergExecution(4, 0)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        execution.begin(plan_order, {}, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        pieces = []
        for step in range(4):
            due = execution.due_pieces(plan_order, {}, 10, pieces, {}, float(step))
            print(f'Step {step + 1}: committed {execution.committed(pieces)}, due {due}')
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
                print(f'  while it rests, due {execution.due_pieces(plan_order, {}, 10, pieces, {}, float(step))}')
                pieces[-1].state = 'filled'
                pieces[-1].filled_quantity = due[0]
        print(f'More to send: {execution.will_send_more({}, 10 - execution.committed(pieces), pieces)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    OnePieceAtATimeExample().run()
