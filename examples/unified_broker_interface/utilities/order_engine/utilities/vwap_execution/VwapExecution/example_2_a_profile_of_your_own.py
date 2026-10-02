"""Sizes a VWAP by a caller's own profile, and shows a moment before the open and one after the last half hour.

A `volume_profile` replaces the default NSE shape. A moment before the 09:15 open counts as the first half hour, and a slice after the profile's last half hour takes the last weight. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/vwap_execution/VwapExecution/example_2_a_profile_of_your_own.py
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


class AProfileOfYourOwnExample:
    """Prints the weights of a VWAP with a three-step profile."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = VwapExecution(4, 120, [1.0, 2.0, 3.0])
        before_open = datetime.datetime(2026, 10, 1, 9, 0, tzinfo=INDIA).timestamp()
        print(f'09:00 falls in half hour {execution.bucket_of(before_open)}')
        start = datetime.datetime(2026, 10, 1, 9, 15, tzinfo=INDIA).timestamp()
        memory = {}
        execution.begin(StandInPlanOrder(), memory, {}, start)
        print(f'From 09:15, slices every {execution.interval()} s take weights {execution.slice_weights(memory)}')
        print(f'Twenty shared out as {execution.slice_quantities(20, memory)}')
        print(f'As a dry run shows it: {execution.described()}')
        closing = VwapExecution(4, None, None)
        closing.until = '15:30'
        closing_memory = {}
        closing.begin(StandInPlanOrder(), closing_memory, {}, datetime.datetime(2026, 10, 1, 15, 10, tzinfo=INDIA).timestamp())
        print(f'Until 15:30, started at 15:10: {closing_memory["over_minutes"]} minutes, a slice every {closing.interval(closing_memory)} s, shown as {closing.described()}')


if __name__ == '__main__':
    AProfileOfYourOwnExample().run()
