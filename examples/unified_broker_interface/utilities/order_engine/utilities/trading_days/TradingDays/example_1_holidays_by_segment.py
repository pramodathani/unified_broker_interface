"""Asks which days in the first weeks of October 2026 trade, for an NSE equity and an MCX commodity future.

`TradingDays` reads the same exchange calendars the tick pipeline uses, which are files in the repository, so this program needs no data store. It walks from Thursday 1 October to Wednesday 21 October 2026 and prints whether each day trades for the `nse_equities` segment and for the `mcx_commodity_futures` segment, and then asks for the next trading day after a few dates.

Notice Gandhi Jayanti on Friday 2 October, which closes both exchanges, so the next trading day after Thursday 1 October is Monday 5 October. Notice also Tuesday 20 October, when NSE is shut for Dussehra but MCX still trades part of the day, so the two segments disagree.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trading_days/TradingDays/example_1_holidays_by_segment.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)


class HolidaysBySegmentExample:
    """Prints a small trading calendar for two segments.

    Attributes:
        trading_days (TradingDays): The calendar reader being shown.
        segments (list): The segments compared.
    """

    def __init__(self):
        """Builds the reader over the repository's calendar files.

        Returns:
            None: This method returns nothing.
        """
        self.trading_days = TradingDays()
        self.segments = [
            'nse_equities',
            'mcx_commodity_futures',
        ]

    def run(self):
        """Prints each day's answer and a few next trading days.

        Returns:
            None: This method returns nothing.
        """
        day = datetime.date(2026, 10, 1)
        last_day = datetime.date(2026, 10, 21)
        while day <= last_day:
            answers = []
            for segment in self.segments:
                answers.append(f'{segment} {self.trading_days.is_trading_day(segment, day)}')
            print(f'{day} {day.strftime("%a")}: {", ".join(answers)}')
            day = day + datetime.timedelta(days=1)
        for after in [
            datetime.date(2026, 10, 1),
            datetime.date(2026, 10, 19),
        ]:
            for segment in self.segments:
                following = self.trading_days.next_trading_day(segment, after)
                print(f'Next {segment} trading day after {after}: {following} {following.strftime("%a")}')


if __name__ == '__main__':
    HolidaysBySegmentExample().run()
