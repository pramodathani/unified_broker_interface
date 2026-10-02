"""Readies a daily copy's trigger when the plan is placed early on a trading morning, and asks it whether it holds either side of its moment.

`TradingDayTimeCondition.prepare` keeps the moment as a Unix time in the condition's memory, so a restart keeps it; placed at 09:00 on Wednesday 23 September 2026, copy 0 at 09:20 goes that same morning. `is_met` holds from that moment on, and `needs_prices` and `instruments` say it reads no quotes, so the clock ticks are what fire it. The moment of placement is fixed here by standing in for the clock. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trading_day_time_condition/TradingDayTimeCondition/example_2_the_moment_and_when_it_holds.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.trading_day_time_condition import (
    TradingDayTimeCondition,
)


class StandInContext:
    """Stands in for the order's view of the plan order: an NSE equity.

    Attributes:
        segment (str): The exchange-prefixed segment, whose calendar is followed.
    """

    def __init__(self):
        """Builds the context.

        Returns:
            None: This method returns nothing.
        """
        self.segment = 'nse_equities'

    def trading_segment(self):
        """The segment.

        Returns:
            str: `nse_equities`.
        """
        return self.segment


class TheMomentAndWhenItHoldsExample:
    """Readies one copy's trigger and asks it about three moments."""

    def run(self):
        """Prints the moment kept and each answer.

        Returns:
            None: This method returns nothing.
        """
        placed = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=moments.INDIA)
        original_now = moments.Moments.now
        moments.Moments.now = lambda self: placed
        try:
            condition = TradingDayTimeCondition('09:20', 0)
            memory = {}
            condition.prepare(StandInContext(), memory)
        finally:
            moments.Moments.now = original_now
        moment = datetime.datetime.fromtimestamp(memory['at'], moments.INDIA)
        print(f'needs prices {condition.needs_prices()}, watches {condition.instruments()}')
        print(f'kept: {memory}, which is {moment:%a %Y-%m-%d %H:%M}')
        offsets = [
            -60,
            0,
            60,
        ]
        for seconds in offsets:
            now = memory['at'] + seconds
            print(f'{seconds:+} seconds: holds {condition.is_met(None, memory, {}, now, "BUY", "BUY")}')
        print(f'with nothing kept: holds {condition.is_met(None, {}, {}, memory["at"], "BUY", "BUY")}')


if __name__ == '__main__':
    TheMomentAndWhenItHoldsExample().run()
