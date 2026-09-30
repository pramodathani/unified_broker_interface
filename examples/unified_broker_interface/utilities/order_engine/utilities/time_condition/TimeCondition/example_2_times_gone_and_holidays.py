"""Shows a time already gone being refused, and a time on a holiday rolling to the next trading day.

A `TimeCondition` works its moment out with the engine's `Moments` clock. On a trading day a time that has already passed is refused with HTTP 400, because an order told to act at a time that has gone is far more likely to be a mistake than an instruction to wait until tomorrow. On a weekend or an exchange holiday the time means that time on the next trading day.

The engine's clock is replaced, in the `time_condition` module, first with a stand-in stopped at 09:30 on Thursday 1 October 2026, and then with one stopped on Friday 2 October 2026, Gandhi Jayanti, an NSE holiday. The trading calendar is read from the calendar files kept in the repository.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/time_condition/TimeCondition/example_2_times_gone_and_holidays.py
"""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
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


class HolidayMoments(Moments):
    """The engine's clock, stopped at 09:30 on Friday 2 October 2026, an NSE holiday."""

    def now(self):
        """The fixed moment.

        Returns:
            datetime.datetime: 09:30 on 2 October 2026, in India.
        """
        return datetime.datetime(2026, 10, 2, 9, 30, tzinfo=INDIA)


class StandInPlanOrder:
    """Stands in for the plan order, whose instrument trades on the NSE."""

    def trading_segment(self):
        """The segment the instrument trades on.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'


class TimesGoneAndHolidaysExample:
    """Prepares time conditions on a trading day and on a holiday."""

    def run(self):
        """Prints what each condition does when it is prepared.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        time_condition.Moments = FixedMoments
        gone = TimeCondition('time_at', '09:15')
        try:
            gone.prepare(plan_order, {})
        except RefusedRequestError as refusal:
            print(f"09:15 at 09:30 on a trading day: refused with HTTP {refusal.status}: {refusal.body['error']}")
        time_condition.Moments = HolidayMoments
        rolled = TimeCondition('time_at', '09:15')
        memory = {}
        rolled.prepare(plan_order, memory)
        print(f"09:15 asked on the holiday falls at {datetime.datetime.fromtimestamp(memory['at'], INDIA)}")
        print(f"Holds at 09:14 that day: {rolled.is_met(plan_order, memory, {}, memory['at'] - 60, 'BUY', 'BUY')}")
        print(f"Holds at 09:15 that day: {rolled.is_met(plan_order, memory, {}, memory['at'], 'BUY', 'BUY')}")
        print(f'Not prepared yet, it never holds: {TimeCondition("time_at", "11:00").is_met(plan_order, {}, {}, 0.0, "BUY", "BUY")}')


if __name__ == '__main__':
    TimesGoneAndHolidaysExample().run()
