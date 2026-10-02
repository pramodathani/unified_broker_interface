"""Builds three slices in the states a nested execution gives them, and shows which count as finished.

A slice is finished when its inner execution will send nothing more and every one of its broker orders has finished: wholly filled, or partly filled and then cancelled. A slice still working, or one whose next iceberg piece is still to go, is not. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/nested_execution/SlicePiece/example_2_finished_or_not.py
"""

from unified_broker_interface.utilities.order_engine.utilities.nested_execution import (
    SlicePiece,
)


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


class FinishedOrNotExample:
    """Prints three slices."""

    def run(self):
        """Prints each slice's state.

        Returns:
            None: This method returns nothing.
        """
        slices = [
            (
                'filled',
                SlicePiece(5, 5, True, 'filled'),
            ),
            (
                'partly filled, the rest cancelled',
                SlicePiece(5, 3, True, 'cancelled'),
            ),
            (
                'its next iceberg piece still to go',
                SlicePiece(5, 2, False, 'working'),
            ),
        ]
        for label, slice_piece in slices:
            print(f'{label}: quantity {slice_piece.quantity}, filled {slice_piece.filled_quantity}, finished {slice_piece.is_finished()}, state {slice_piece.state}')


if __name__ == '__main__':
    FinishedOrNotExample().run()
