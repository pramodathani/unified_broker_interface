"""Shows a time given on an exchange holiday moving to the next trading day, and the times `Moments` refuses.

Friday 2 October 2026 is Gandhi Jayanti, when NSE is shut, and the weekend follows it. An order placed that morning to act at 15:00 cannot act until Monday 5 October, so `time_on_trading_day` answers with Monday's 15:00, and `described` shows the date beside the time so the caller sees which day was meant. This program pins the current moment to 10:00 that Friday by passing `now=`.

It then shows the three refusals, each a `RefusedRequestError` carrying an HTTP 400 body for the order route to send back: a time that has already passed on a trading day, text that is not a time, and a duration that is not a positive number of minutes. The holidays come from the repository's calendar files, so nothing is read from a data store.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/moments/Moments/example_2_holidays_and_refusals.py
"""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)


class HolidaysAndRefusalsExample:
    """Reads times on a holiday and prints the refusals for bad ones.

    Attributes:
        moments (Moments): The reader being shown.
        holiday_morning (datetime.datetime): 10:00 on Gandhi Jayanti.
        trading_afternoon (datetime.datetime): 16:00 on the following Monday, after the square-off time.
    """

    def __init__(self):
        """Builds the reader and the two pinned moments.

        Returns:
            None: This method returns nothing.
        """
        self.moments = Moments()
        self.holiday_morning = datetime.datetime(2026, 10, 2, 10, 0, 0, tzinfo=INDIA)
        self.trading_afternoon = datetime.datetime(2026, 10, 5, 16, 0, 0, tzinfo=INDIA)

    def run(self):
        """Prints the moved time and each refusal.

        Returns:
            None: This method returns nothing.
        """
        moment, day = self.moments.time_on_trading_day('15:00', 'act_at', 'nse_equities', self.holiday_morning)
        shown = datetime.datetime.fromtimestamp(moment, INDIA).isoformat()
        print(f'15:00 asked on {self.holiday_morning.date()}: {shown}')
        print(f'Described: {self.moments.described("15:00", day, self.holiday_morning)}')
        attempts = [
            (
                'time_today 15:10 at 16:00',
                self.moments.time_today,
                (
                    '15:10',
                    'square_off_at',
                    self.trading_afternoon,
                ),
            ),
            (
                'time_on_trading_day 15:10 at 16:00',
                self.moments.time_on_trading_day,
                (
                    '15:10',
                    'square_off_at',
                    'nse_equities',
                    self.trading_afternoon,
                ),
            ),
            (
                'read_time of 3pm',
                self.moments.read_time,
                (
                    '3pm',
                    'square_off_at',
                ),
            ),
            (
                'minutes_from_now of -5',
                self.moments.minutes_from_now,
                (
                    -5,
                    'cancel_after_minutes',
                    self.trading_afternoon,
                ),
            ),
        ]
        for description, method, arguments in attempts:
            try:
                method(*arguments)
            except RefusedRequestError as error:
                print(f'{description}: refused with {error.status}: {error.body["error"]}')


if __name__ == '__main__':
    HolidaysAndRefusalsExample().run()
