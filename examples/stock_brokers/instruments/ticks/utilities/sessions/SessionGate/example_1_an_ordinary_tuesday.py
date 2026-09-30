"""Asks the session gate which ticks of an ordinary Tuesday would be kept, for each kind of session.

The unified tick service drops any tick received outside its instrument's window, because brokers keep streaming outside trading hours: a Sunday reconnect replays Friday's prices and the Saturday mock sessions stream prices that never traded. `SessionGate.in_window` answers that question for one instant. The window is wider than trading hours on both sides: it opens at 09:00 for the pre-open auction and closes after the session to keep the closing prices, so an equity tick at 15:45 is kept although trading ended at 15:30.

`before_trading_close` is a separate question: whether an instant is before the session's own close, which decides whether a broker's `close` may be taken as the previous close. The program uses an empty calendar, so the answer depends only on the clock and the weekday, and it builds each instant from a fixed India time. No data store is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/sessions/SessionGate/example_1_an_ordinary_tuesday.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks.utilities import sessions
from stock_brokers.instruments.ticks.utilities.sessions import (
    SessionGate,
    TradingCalendar,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class OrdinaryTuesdayExample:
    """Checks a series of instants on Tuesday 2026-09-15 against three sessions.

    Attributes:
        gate (SessionGate): The gate being shown, over an empty calendar.
    """

    def __init__(self):
        """Builds the gate over a calendar with no holidays.

        Returns:
            None: This method returns nothing.
        """
        self.gate = SessionGate(TradingCalendar.empty())

    def check(self, exchange, segment, hour, minute):
        """Prints whether a tick at a time on the Tuesday is kept, and whether it is before the close.

        Args:
            exchange (str): The canonical exchange.
            segment (str): The instrument's canonical segment.
            hour (int): The hour, India time.
            minute (int): The minute.

        Returns:
            None: This method returns nothing.
        """
        session = sessions.session_for(segment)
        moment = datetime.datetime(2026, 9, 15, hour, minute, tzinfo=INDIA)
        epoch = moment.timestamp()
        kept = self.gate.in_window(exchange, session, epoch)
        before_close = self.gate.before_trading_close(session, epoch)
        print(f'{segment} at {hour:02d}:{minute:02d}: kept {kept}, before the close {before_close}')

    def run(self):
        """Prints the answers for an equity, a currency and a commodity instrument.

        Returns:
            None: This method returns nothing.
        """
        self.check('nse', 'nse_equities', 8, 55)
        self.check('nse', 'nse_equities', 9, 5)
        self.check('nse', 'nse_equities', 15, 45)
        self.check('nse', 'nse_equities', 16, 5)
        self.check('nse', 'nse_currency_futures', 16, 45)
        self.check('nse', 'nse_currency_futures', 17, 40)
        self.check('mcx', 'mcx_commodity_futures', 17, 40)
        self.check('mcx', 'mcx_commodity_futures', 23, 58)
        sunday = datetime.datetime(2026, 9, 13, 11, 0, tzinfo=INDIA)
        kept = self.gate.in_window('nse', sessions.EQUITY_SESSION, sunday.timestamp())
        print(f'nse_equities on Sunday 2026-09-13 at 11:00: kept {kept}')


if __name__ == '__main__':
    OrdinaryTuesdayExample().run()
