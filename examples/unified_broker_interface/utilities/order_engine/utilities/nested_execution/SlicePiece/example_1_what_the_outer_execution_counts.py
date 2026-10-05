"""Shows a TWAP counting the slices it has released when they are given to it as `SlicePiece`s rather than broker orders.

A timed execution counts what it has sent by the pieces' quantities and their number, so two released slices of five are, to it, ten units in two pieces: nothing more is due and it will send no more. `is_finished` tells it whether a slice can still fill. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/nested_execution/SlicePiece/example_1_what_the_outer_execution_counts.py
"""

from unified_broker_interface.utilities.order_engine.utilities.nested_execution import (
    SlicePiece,
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


class WhatTheOuterExecutionCountsExample:
    """Hands a TWAP two slices."""

    def run(self):
        """Prints what the TWAP makes of them.

        Returns:
            None: This method returns nothing.
        """
        twap = TwapExecution(2, 1.0)
        memory = {}
        twap.begin(None, memory, {}, 0.0)
        released = [
            SlicePiece(5, 5, True, 'filled'),
            SlicePiece(5, 2, False, 'working'),
        ]
        for slice_piece in released:
            print(f'slice of {slice_piece.quantity}: filled {slice_piece.filled_quantity}, finished {slice_piece.is_finished()}')
        print(f'due at 45s: {twap.due_pieces(StandInPlanOrder(), memory, 10, released, {}, 45.0)}')
        print(f'will send more: {twap.will_send_more(memory, 0, released)}')


if __name__ == '__main__':
    WhatTheOuterExecutionCountsExample().run()
