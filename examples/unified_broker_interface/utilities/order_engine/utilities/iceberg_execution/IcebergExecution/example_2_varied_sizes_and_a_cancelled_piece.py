"""Shows an iceberg's pieces varied by up to a fifth, and an iceberg that stops once a piece is cancelled.

With `randomise_percent`, `IcebergExecution.piece_size` varies each piece by up to that share either way, worked out from the parent's id and how many pieces have gone, so the sizes are the same every time they are worked out but follow no visible pattern. A piece that is cancelled or rejected rather than filled stops the iceberg. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/iceberg_execution/IcebergExecution/example_2_varied_sizes_and_a_cancelled_piece.py
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


class VariedSizesAndACancelledPieceExample:
    """Prints varied piece sizes and an iceberg that stops."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = IcebergExecution(100, 20)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        pieces = []
        sizes = []
        for number in range(5):
            sizes.append(execution.piece_size(plan_order, pieces))
            pieces.append(maker.piece(number + 1, 100, 'filled', 100))
        print(f'Five piece sizes around 100: {sizes}')
        stopped = [
            maker.piece(1, 4, 'filled', 4),
            maker.piece(2, 4, 'cancelled', 1),
        ]
        print(f'After a cancelled piece: due {execution.due_pieces(plan_order, {}, 10, stopped, {}, 0.0)}, more to send {execution.will_send_more({}, 5, stopped)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    VariedSizesAndACancelledPieceExample().run()
