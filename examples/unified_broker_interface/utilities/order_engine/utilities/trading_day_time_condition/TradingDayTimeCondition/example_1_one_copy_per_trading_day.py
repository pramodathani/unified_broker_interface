"""Works out which trading day each of four daily copies goes on, for a plan placed on a Wednesday morning and on a Thursday before a holiday.

`TradingDayTimeCondition.day` starts from today when today trades and the time has not passed, and otherwise from the next trading day, then counts `day_index` trading days on, skipping weekends and the exchange's holidays from its calendar files. Placed at 10:00 on Wednesday 23 September 2026, a 09:20 copy cannot go that day, so copy 0 goes on Thursday. Placed on Thursday 1 October, the next trading day is Monday 5 October, because 2 October is a holiday. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trading_day_time_condition/TradingDayTimeCondition/example_1_one_copy_per_trading_day.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.trading_day_time_condition import (
    TradingDayTimeCondition,
)


class OneCopyPerTradingDayExample:
    """Prints the day of each copy for two placements."""

    def run(self):
        """Prints each copy's day.

        Returns:
            None: This method returns nothing.
        """
        placements = [
            datetime.datetime(2026, 9, 23, 10, 0, tzinfo=moments.INDIA),
            datetime.datetime(2026, 10, 1, 10, 0, tzinfo=moments.INDIA),
        ]
        for now in placements:
            print(f'Placed {now:%a %Y-%m-%d %H:%M}:')
            for index in range(4):
                condition = TradingDayTimeCondition('09:20', index)
                print(f'  copy {index}: {condition.day("nse_equities", now):%a %Y-%m-%d}, {condition.described()}')


if __name__ == '__main__':
    OneCopyPerTradingDayExample().run()
