"""Shows when the Fyers candle download pauses for trading hours, and that a stop request ends the pause at once.

Every Fyers request counts toward the app's 200 a minute, shared with the pollers and orders, so the history download stays out of trading hours: 09:00 to 23:55 India time, Monday to Friday, from the equity pre-open to the latest close of MCX's evening session. Weekends are free all day, and `daily_cap` raises the cap there from 45,000 requests to 100,000. `seconds_until_trading_ends` says how long the pause lasts from a given moment, and `claim` waits it out before claiming a series, on the stop event `run` remembers, so `systemctl stop` does not have to wait. This program builds the downloader without logging in or opening a database, which is enough for these two methods.

Notice that 08:59 and 23:55 on a Wednesday, and noon on a Saturday, have no pause, and that the stopped claim returns None within a fraction of a second.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/fyers/FyersCandles/example_3_trading_hours_pause.py
"""

import datetime
import logging
import threading
import time

from stock_brokers.instruments.historical.base import INDIA_TIMEZONE
from stock_brokers.instruments.historical.fyers import FyersCandles


class ClockedFyersCandles(FyersCandles):
    """The Fyers downloader built without a session or a database, with its clock fixed at noon on Wednesday 2026-09-30."""

    def __init__(self):
        """Builds the downloader with only a logger.

        Returns:
            None: This method returns nothing.
        """
        self._logger = logging.getLogger('example')
        self._logger.addHandler(logging.NullHandler())
        self._logger.propagate = False

    def seconds_until_trading_ends(self, now=None):
        """The pause from noon on Wednesday 2026-09-30, whatever the real time.

        Args:
            now (datetime.datetime | None): Ignored.

        Returns:
            float: The seconds until 23:55.
        """
        del now
        noon = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=INDIA_TIMEZONE)
        return super().seconds_until_trading_ends(noon)


class TradingHoursPauseExample:
    """Prints the pause at several moments and stops a paused claim.

    Attributes:
        candles (ClockedFyersCandles): The downloader.
    """

    def __init__(self):
        """Builds the downloader.

        Returns:
            None: This method returns nothing.
        """
        self.candles = ClockedFyersCandles()

    def run(self):
        """Prints the pause at six moments, then stops a run whose claim is paused.

        Returns:
            None: This method returns nothing.
        """
        moments = [
            ('Wednesday 08:59', datetime.datetime(2026, 9, 30, 8, 59, tzinfo=INDIA_TIMEZONE)),
            ('Wednesday 09:00', datetime.datetime(2026, 9, 30, 9, 0, tzinfo=INDIA_TIMEZONE)),
            ('Wednesday 15:30', datetime.datetime(2026, 9, 30, 15, 30, tzinfo=INDIA_TIMEZONE)),
            ('Wednesday 23:55', datetime.datetime(2026, 9, 30, 23, 55, tzinfo=INDIA_TIMEZONE)),
            ('Saturday 12:00', datetime.datetime(2026, 10, 3, 12, 0, tzinfo=INDIA_TIMEZONE)),
            ('Sunday 20:00', datetime.datetime(2026, 10, 4, 20, 0, tzinfo=INDIA_TIMEZONE)),
        ]
        for label, moment in moments:
            pause = FyersCandles.seconds_until_trading_ends(self.candles, moment)
            print(f'{label}: pause for {pause / 3600:.2f} hours')
        for label, moment in [moments[2], moments[4]]:
            print(f'Daily cap on {label}: {self.candles.daily_cap(moment)}')
        stop_event = threading.Event()
        stop_event.set()
        visits, bars = self.candles.run(stop_event=stop_event)
        print(f'A run asked to stop before it starts: {visits} windows, {bars} bars')
        stop_event.clear()
        threading.Timer(0.2, stop_event.set).start()
        started = time.monotonic()
        claimed = self.candles.claim()
        waited = time.monotonic() - started
        print(f'A claim at noon, stopped after 0.2 s: {claimed}, back within a second: {waited < 1}')


if __name__ == '__main__':
    TradingHoursPauseExample().run()
