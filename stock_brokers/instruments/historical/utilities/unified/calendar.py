"""
The days each exchange traded, taken from the bars already stored.

No exchange holiday list is kept, because the stored bars already say which days traded, special
sessions included: the Budget sessions on Saturday 2020-02-01, 2025-02-01 and Sunday 2026-02-01, the
Muhurat session on Sunday 2023-11-12, and the Saturday disaster recovery sessions of 2024.

A date is a trading day for an exchange when either of two sources says so:

- zerodha's daily bar for the exchange's benchmark index exists - NIFTY 50 for NSE, SENSEX for BSE,
  both back to 2005; or
- flattrade has daily bars on that date for at least a tenth of the series it had on the busiest
  day of that month.

The second condition exists for days the index bar is missing, and its threshold is what keeps
out the bars that are not sessions at all: seven BSE series with bars on Saturdays through 2026,
and two NSE series with Tuesday-only bars through the 2021-22 winter.

Intraday bars are held to the same days and additionally to the session grid, which starts at
09:15 India time.
"""

import datetime

from stock_brokers.instruments.historical.base import INDIA_TIMEZONE
from stock_brokers.instruments.historical.utilities.unified.sources import INTRADAY_MINUTES
from utilities.configurations import get_postgres

# zerodha tokens of each exchange's benchmark index.
BENCHMARK_TOKENS = {
    "nse": "256265",  # NIFTY 50
    "bse": "265",     # SENSEX
}

# A flattrade date counts when it has at least this share of the month's busiest day.
MINIMUM_SHARE_OF_MONTH = 0.10

# The first bar of the Indian cash session.
SESSION_START = datetime.time(9, 15)

class TradingCalendar:
    """
    Trading days per exchange, loaded once per exchange and kept.

    Attributes:
        days (dict): Exchange to a set of datetime.date, filled on first use.
    """

    def __init__(self):
        """
        Build an empty calendar; exchanges are loaded when first asked for.

        Returns:
            None: This function returns nothing.
        """
        self.days = {}

    def trading_days(self, exchange):
        """
        Every date an exchange traded on, as far back as the stored bars go.

        Args:
            exchange (str): The canonical exchange, "nse" or "bse".

        Returns:
            set[datetime.date]: The trading dates.
        """
        if exchange not in self.days:
            self.days[exchange] = self.load(exchange)
        return self.days[exchange]

    def is_trading_day(self, exchange, day):
        """
        Whether an exchange traded on a date.

        Args:
            exchange (str): The canonical exchange.
            day (datetime.date): The date.

        Returns:
            bool: True if it traded.
        """
        return day in self.trading_days(exchange)

    @staticmethod
    def load(exchange):
        """
        Read an exchange's trading days from the stored bars.

        Args:
            exchange (str): The canonical exchange, "nse" or "bse".

        Returns:
            set[datetime.date]: The trading dates.
        """
        days = set()
        connection = get_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT (\"time\" AT TIME ZONE 'Asia/Kolkata')::date "
                    "FROM zerodha.price_history WHERE instrument_token = %s AND \"interval\" = 'day'",
                    (BENCHMARK_TOKENS[exchange],))
                for (day,) in cursor.fetchall():
                    days.add(day)

                cursor.execute(
                    "SELECT (\"time\" AT TIME ZONE 'Asia/Kolkata')::date AS day, count(*) "
                    "FROM flattrade.price_history "
                    "WHERE \"interval\" = 'day' AND instrument_token LIKE %s "
                    "GROUP BY 1",
                    (exchange.upper() + "|%",))
                counts = dict(cursor.fetchall())
        finally:
            connection.close()

        busiest = {}
        for day, count in counts.items():
            month = (day.year, day.month)
            busiest[month] = max(busiest.get(month, 0), count)
        for day, count in counts.items():
            if count >= MINIMUM_SHARE_OF_MONTH * busiest[(day.year, day.month)]:
                days.add(day)
        return days

def on_grid(moment, interval):
    """
    Whether a bar's timestamp sits where its interval's bars start.

    Daily bars sit at midnight India time. Intraday bars start at 09:15 India time and every
    interval's length after it.

    Args:
        moment (datetime.datetime): The bar's timezone aware timestamp.
        interval (str): The stored interval name.

    Returns:
        bool: True if the bar is on the grid.
    """
    local = moment.astimezone(INDIA_TIMEZONE)
    if interval == "day":
        return local.hour == 0 and local.minute == 0 and local.second == 0
    minutes = INTRADAY_MINUTES.get(interval)
    if minutes is None:
        return False
    since_open = (local.hour * 60 + local.minute) - (SESSION_START.hour * 60 + SESSION_START.minute)
    return local.second == 0 and since_open >= 0 and since_open % minutes == 0
