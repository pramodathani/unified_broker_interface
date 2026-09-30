"""Works out when two time conditions fall, and asks them whether they hold at moments through the morning.

A `TimeCondition` ties a plan order's trigger to a time of day on the instrument's next trading day. `time_after` holds from the time onwards, and `time_before` holds until it, which is how a price trigger is kept to part of the day inside `all`. The time is worked out once, by `prepare`, when the plan is placed.

The engine's clock is replaced, in the `time_condition` module, with a stand-in stopped at 09:30 on Thursday 1 October 2026, so every answer is the same whenever the program runs. The trading calendar is read from the calendar files kept in the repository.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/time_condition/TimeCondition/example_1_after_and_before.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import (
    time_condition,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.time_condition import (
    TimeCondition,
)

ASKED_AT = datetime.datetime(2026, 10, 1, 9, 30, tzinfo=INDIA)


class FixedMoments(Moments):
    """The engine's clock, stopped at 09:30 on Thursday 1 October 2026, a trading day."""

    def now(self):
        """The fixed moment.

        Returns:
            datetime.datetime: 09:30 on 1 October 2026, in India.
        """
        return ASKED_AT


class StandInPlanOrder:
    """Stands in for the plan order, whose instrument trades on the NSE."""

    def trading_segment(self):
        """The segment the instrument trades on.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'


class AfterAndBeforeExample:
    """Prepares an after and a before condition and asks them at four moments."""

    def run(self):
        """Prints when each condition falls and whether it holds at each moment.

        Returns:
            None: This method returns nothing.
        """
        time_condition.Moments = FixedMoments
        plan_order = StandInPlanOrder()
        after = TimeCondition('time_after', '10:00')
        before = TimeCondition('time_before', '15:00')
        after_memory = {}
        before_memory = {}
        after.prepare(plan_order, after_memory)
        before.prepare(plan_order, before_memory)
        print(f'Reads quotes: {after.needs_prices()}, watches: {after.instruments()}')
        print(f"after 10:00 falls at {datetime.datetime.fromtimestamp(after_memory['at'], INDIA)}")
        print(f"before 15:00 falls at {datetime.datetime.fromtimestamp(before_memory['at'], INDIA)}")
        for hour, minute in ((9, 45), (10, 0), (14, 59), (15, 0)):
            moment = datetime.datetime(2026, 10, 1, hour, minute, tzinfo=INDIA).timestamp()
            after_met = after.is_met(plan_order, after_memory, {}, moment, 'BUY', 'BUY')
            before_met = before.is_met(plan_order, before_memory, {}, moment, 'BUY', 'BUY')
            print(f'{hour:02d}:{minute:02d}: after 10:00 {after_met}, before 15:00 {before_met}')
        print(f'As a dry run shows them: {after.described()} and {before.described()}')


if __name__ == '__main__':
    AfterAndBeforeExample().run()
