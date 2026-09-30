"""Turns the times an order is told to act at into moments, on an ordinary trading day.

An order such as "square off at 15:10" or "cancel in 30 minutes" gives a wall-clock time or a duration, and the engine needs an epoch to compare against its clock. `Moments` reads the text in Indian time whatever the machine's own timezone is. This program pins the current moment to 11:00 in India on Thursday 1 October 2026, a normal NSE trading day, by passing `now=` to every method, so the output is the same whenever it runs.

Nothing here reads a data store; the exchange holidays come from the calendar files in the repository. Notice that the epochs printed for 15:10 by `time_today` and by `time_on_trading_day` agree, because today trades, and that `described` shows only the caller's own text for a time today. The program calls `now` once too, but prints only its timezone, since the actual moment changes on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/moments/Moments/example_1_times_on_a_trading_day.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)


class TimesOnATradingDayExample:
    """Reads a square-off time and a duration against a pinned moment on a trading day.

    Attributes:
        moments (Moments): The reader being shown.
        now (datetime.datetime): The pinned current moment.
    """

    def __init__(self):
        """Builds the reader and pins the moment to 11:00 India time on 1 October 2026.

        Returns:
            None: This method returns nothing.
        """
        self.moments = Moments()
        self.now = datetime.datetime(2026, 10, 1, 11, 0, 0, tzinfo=INDIA)

    def run(self):
        """Prints the moments worked out from each piece of text.

        Returns:
            None: This method returns nothing.
        """
        print(f'The real now is kept in: {self.moments.now().tzinfo}')
        print(f'Pinned now: {self.now.isoformat()} ({self.now.timestamp():.0f})')
        wanted = self.moments.read_time('15:10:30', 'square_off_at')
        print(f'read_time of 15:10:30: {wanted!r}')
        square_off = self.moments.time_today('15:10', 'square_off_at', self.now)
        shown = datetime.datetime.fromtimestamp(square_off, INDIA).isoformat()
        print(f'time_today of 15:10: {square_off:.0f} ({shown})')
        moment, day = self.moments.time_on_trading_day('15:10', 'square_off_at', 'nse_equities', self.now)
        print(f'time_on_trading_day of 15:10 for nse_equities: {moment:.0f} on {day}')
        print(f'Described: {self.moments.described("15:10", day, self.now)}')
        expiry = self.moments.minutes_from_now('30', 'cancel_after_minutes', self.now)
        shown = datetime.datetime.fromtimestamp(expiry, INDIA).isoformat()
        print(f'minutes_from_now of 30: {expiry:.0f} ({shown})')
        expiry = self.moments.minutes_from_now(2.5, 'cancel_after_minutes', self.now)
        print(f'minutes_from_now of 2.5 is {expiry - self.now.timestamp():.0f} seconds ahead')


if __name__ == '__main__':
    TimesOnATradingDayExample().run()
