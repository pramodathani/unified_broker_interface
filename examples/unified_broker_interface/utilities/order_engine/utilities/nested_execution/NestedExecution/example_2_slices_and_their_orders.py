"""Shows how a nested execution tells its slices apart: which broker orders belong to each, and how each slice looks to the outer execution.

`slice_legs` reads `leg_slices` to find one slice's broker orders, and `slice_pieces` turns every released slice into a `SlicePiece`, finished only once its iceberg will send nothing more and all its broker orders have finished. While the first slice's last piece rests, the order is not finished, so `will_send_more` is True even after the outer TWAP has released everything. Stand-in broker orders are filled by hand, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/nested_execution/NestedExecution/example_2_slices_and_their_orders.py
"""

from unified_broker_interface.utilities.order_engine.utilities.iceberg_execution import (
    IcebergExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.nested_execution import (
    NestedExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.twap_execution import (
    TwapExecution,
)


class StandInPlanOrder:
    """Stands in for the plan order an execution is asked about, which here only answers the lot."""

    def lot_size(self):
        """The lot every slice must be a whole number of, which for a share is one.

        Returns:
            int: One.
        """
        return 1


class StandInLeg:
    """Stands in for one broker order: its quantity, what it filled and whether it has finished.

    Attributes:
        quantity (int): The quantity sent.
        filled_quantity (int): What has filled.
        finished (bool): Whether it can fill no more.
        state (str): `acknowledged` while resting, `filled` once filled.
    """

    def __init__(self, quantity):
        """Builds a resting broker order.

        Args:
            quantity (int): The quantity sent.

        Returns:
            None: This method returns nothing.
        """
        self.quantity = quantity
        self.filled_quantity = 0
        self.finished = False
        self.state = 'acknowledged'

    def fill(self):
        """Fills it completely.

        Returns:
            None: This method returns nothing.
        """
        self.filled_quantity = self.quantity
        self.finished = True
        self.state = 'filled'

    def is_finished(self):
        """Whether it can fill no more.

        Returns:
            bool: True once filled.
        """
        return self.finished


class SlicesAndTheirOrdersExample:
    """Builds memory for two slices by hand and reads it back."""

    def run(self):
        """Prints each slice's orders and how it looks to the outer execution.

        Returns:
            None: This method returns nothing.
        """
        execution = NestedExecution(TwapExecution(2, 1.0), IcebergExecution(2, 0))
        memory = {}
        execution.begin(None, memory, {}, 0.0)
        legs = []
        moments = [
            0.0,
            30.0,
        ]
        for now in moments:
            for quantity in execution.due_pieces(StandInPlanOrder(), memory, 10, legs, {}, now):
                legs.append(StandInLeg(quantity))
        legs[0].fill()
        for index in range(len(memory['slices'])):
            print(f'slice {index}: orders of {[leg.quantity for leg in execution.slice_legs(memory, legs, index)]}')
        for index, slice_piece in enumerate(execution.slice_pieces(memory, legs)):
            print(f'slice {index} to the outer execution: quantity {slice_piece.quantity}, filled {slice_piece.filled_quantity}, finished {slice_piece.is_finished()}, state {slice_piece.state}')
        print(f'more to send: {execution.will_send_more(memory, 8, legs)}')


if __name__ == '__main__':
    SlicesAndTheirOrdersExample().run()
