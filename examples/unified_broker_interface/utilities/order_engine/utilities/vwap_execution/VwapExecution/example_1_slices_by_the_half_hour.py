"""Sizes a VWAP's three slices from 10:00 by the half hour each falls in, with the default NSE profile.

`VwapExecution` gives each slice the weight of the half hour from the 09:15 open that it falls in: 10:00 is in the second half hour, weighted 0.095, and 10:20 and 10:40 in the third, weighted 0.075, so the first slice is the biggest. `bucket_of` says which half hour a moment falls in, counting from zero. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/vwap_execution/VwapExecution/example_1_slices_by_the_half_hour.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.vwap_execution import (
    VwapExecution,
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

    def trading_segment(self):
        """The segment the order trades in, which sets when the session opens.

        Returns:
            str: NSE equities, which open at 09:15.
        """
        return 'nse_equities'


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


class SlicesByTheHalfHourExample:
    """Walks a VWAP from 10:00 on 1 October 2026."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = VwapExecution(3, 60, None)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        start = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=INDIA).timestamp()
        memory = {}
        execution.begin(plan_order, memory, {}, start)
        for minutes in (0, 20, 40):
            print(f'10:{minutes:02d} falls in half hour {execution.bucket_of(start + minutes * 60)}')
        print(f'Weights {execution.slice_weights(memory)}, ten shared out as {execution.slice_quantities(10, memory)}')
        pieces = []
        for minutes in (0, 20, 40):
            due = execution.due_pieces(plan_order, memory, 10, pieces, {}, start + minutes * 60)
            if due:
                pieces.append(maker.piece(len(pieces) + 1, due[0], 'acknowledged', 0))
            print(f'10:{minutes:02d}: due {due}')


if __name__ == '__main__':
    SlicesByTheHalfHourExample().run()
