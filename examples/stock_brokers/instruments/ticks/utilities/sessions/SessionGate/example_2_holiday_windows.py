"""Shows how holidays that close only part of a day change a session's window, using the exchanges' real 2026 calendar.

`SessionGate.window` works out, once per exchange, session and India day, which seconds after midnight accept ticks, and remembers it. A full holiday or a weekend has no window. A commodity day whose morning is closed opens at 17:00 for the evening session. A commodity day whose evening is closed keeps the morning session and stays open 30 minutes past 17:00 for the morning's closing prices. `is_trading_day` asks only whether a day has any window, and `window_end_epoch` gives the instant the window around a moment closes, which the ownership rules use to know how long an owner's claim lasts.

The program loads the calendar files in the repository and asks about Ganesh Chaturthi (Monday 2026-09-14), New Year's Day and an ordinary Tuesday. Day numbers are whole days since 1970-01-01 in India time, computed from fixed dates. No data store is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/sessions/SessionGate/example_2_holiday_windows.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks.utilities import sessions
from stock_brokers.instruments.ticks.utilities.sessions import (
    SessionGate,
    TradingCalendar,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class HolidayWindowsExample:
    """Prints the windows of a few days, with the real 2026 calendar.

    Attributes:
        gate (SessionGate): The gate being shown.
    """

    def __init__(self):
        """Builds the gate over the calendar files in the repository.

        Returns:
            None: This method returns nothing.
        """
        self.gate = SessionGate(TradingCalendar.load())

    def clock(self, seconds):
        """Formats seconds after midnight as a clock time.

        Args:
            seconds (int): Seconds after midnight.

        Returns:
            str: The time as HH:MM:SS.
        """
        hours = seconds // 3600
        minutes = seconds % 3600 // 60
        remaining = seconds % 60
        return f'{hours:02d}:{minutes:02d}:{remaining:02d}'

    def describe(self, exchange, session, day):
        """Prints one day's window, whether it trades, and when a window around noon ends.

        Args:
            exchange (str): The canonical exchange.
            session (Session): The session, from `session_for`.
            day (datetime.date): The date.

        Returns:
            None: This method returns nothing.
        """
        noon = datetime.datetime(day.year, day.month, day.day, 12, 0, tzinfo=INDIA)
        day_number = sessions.india_day_number(noon.timestamp())
        window = self.gate.window(exchange, session, day_number)
        trades = self.gate.is_trading_day(exchange, session, day_number)
        if window is None:
            print(f'{day} {exchange} {session.calendar}: trades {trades}, no window')
            return
        print(f'{day} {exchange} {session.calendar}: trades {trades}, window {self.clock(window[0])} to {self.clock(window[1])}')
        ends = self.gate.window_end_epoch(exchange, session, noon.timestamp())
        ends_at = datetime.datetime.fromtimestamp(ends, INDIA)
        print(f'    a tick at noon belongs to a window ending {ends_at.isoformat()}')

    def run(self):
        """Prints the windows for the chosen days.

        Returns:
            None: This method returns nothing.
        """
        ganesh_chaturthi = datetime.date(2026, 9, 14)
        new_year = datetime.date(2026, 1, 1)
        tuesday = datetime.date(2026, 9, 15)
        self.describe('nse', sessions.EQUITY_SESSION, ganesh_chaturthi)
        self.describe('mcx', sessions.COMMODITY_SESSION, ganesh_chaturthi)
        self.describe('mcx', sessions.COMMODITY_SESSION, new_year)
        self.describe('nse', sessions.EQUITY_SESSION, new_year)
        self.describe('ncdex', sessions.NCDEX_SESSION, tuesday)
        self.describe('nse', sessions.CURRENCY_SESSION, tuesday)


if __name__ == '__main__':
    HolidayWindowsExample().run()
