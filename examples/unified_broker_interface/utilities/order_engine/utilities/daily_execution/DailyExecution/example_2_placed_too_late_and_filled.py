"""Shows a daily stop placed after its time, which waits for the next trading morning, and one whose stop has filled, which sends no more.

Placed at 10:00, after 09:20, `DailyExecution.begin` counts today as done. Once any stop has filled, the position is closed, so `will_send_more` is false and `traded` says how much filled. The moments are fixed so the output does not change. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/daily_execution/DailyExecution/example_2_placed_too_late_and_filled.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.daily_execution import (
    DailyExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


class StandInContext:
    """Stands in for the order's view of the plan order, which names its segment."""

    def trading_segment(self):
        """The segment whose calendar the order follows.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'


class PlacedTooLateAndFilledExample:
    """Prints a late daily stop and a filled one."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = DailyExecution('09:20')
        memory = {}
        placed = datetime.datetime(2026, 9, 23, 10, 0, tzinfo=moments.INDIA).timestamp()
        execution.begin(StandInContext(), memory, {}, placed)
        print(f"Today's time to send: {execution.arm_moment(datetime.date(2026, 9, 23)).strftime('%H:%M %Z')}")
        print(f'Placed at 10:00: memory {memory}, due at 10:01 {execution.due_pieces(None, memory, 10, [], {}, placed + 60)}')
        print(f'Next morning at 09:20: due {execution.due_pieces(None, memory, 10, [], {}, placed + 23 * 3600 + 20 * 60)}')
        stop = OrderLeg('parent-1:1', 'root')
        stop.quantity = 10
        stop.filled_quantity = 10
        stop.state = 'filled'
        print(f'After the stop filled: traded {execution.traded([stop])}, more to send {execution.will_send_more(memory, 0, [stop])}')


if __name__ == '__main__':
    PlacedTooLateAndFilledExample().run()
