"""Walks a daily stop placed at 08:45 on a Wednesday through three mornings, a weekend and a day it is asked twice.

`DailyExecution.begin` keeps the instrument's calendar; placed before 09:20 on a trading day, today counts. `due_pieces` sends the order once a trading day, at or after `arm_at`, and remembers the day in `armed_on`, so a second tick that morning sends nothing and a weekend sends nothing. The moments are fixed so the output does not change. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/daily_execution/DailyExecution/example_1_a_stop_each_morning.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.daily_execution import (
    DailyExecution,
)


class StandInContext:
    """Stands in for the order's view of the plan order, which names its segment."""

    def trading_segment(self):
        """The segment whose calendar the order follows.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'


class AStopEachMorningExample:
    """Walks a daily stop through several mornings."""

    def moment(self, day, hour, minute):
        """A moment in India in September 2026, as a Unix time.

        Args:
            day (int): The day of the month.
            hour (int): The hour.
            minute (int): The minute.

        Returns:
            float: The Unix time.
        """
        return datetime.datetime(2026, 9, day, hour, minute, tzinfo=moments.INDIA).timestamp()

    def run(self):
        """Prints each tick.

        Returns:
            None: This method returns nothing.
        """
        execution = DailyExecution('09:20')
        memory = {}
        execution.begin(StandInContext(), memory, {}, self.moment(23, 8, 45))
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}, memory {memory}')
        for label, day, hour, minute in (('Wednesday 09:10', 23, 9, 10), ('Wednesday 09:21', 23, 9, 21), ('Wednesday 09:30', 23, 9, 30), ('Thursday 09:20', 24, 9, 20), ('Saturday 09:30', 26, 9, 30), ('Monday 09:25', 28, 9, 25)):
            print(f'{label}: due {execution.due_pieces(None, memory, 10, [], {}, self.moment(day, hour, minute))}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    AStopEachMorningExample().run()
