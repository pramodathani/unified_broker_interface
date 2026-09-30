"""Works out which days NSE traded from the bars already stored, including a Sunday budget session.

The unified price history keeps no holiday list. `TradingCalendar.load` reads two things from PostgreSQL instead: the dates on which Zerodha stored a daily bar for NSE's benchmark index, NIFTY 50, and how many Flattrade daily series have a bar on each date. A date counts when the index has a bar, or when Flattrade has bars for at least a tenth of the series it had on the busiest day of that month. The second rule catches a day whose index bar is missing, and its threshold keeps out a handful of stray bars on a day that was not a session.

`load` opens its own connection through `get_postgres`, and the example runner points PostgreSQL at a closed port, so this program replaces `get_postgres` in the calendar module with a stand-in that returns an in-memory connection. That connection answers the two queries with a fortnight of recorded-looking rows and counts the queries it is sent. What to notice: Sunday 2026-02-01, the Union Budget session, trades because the index has a bar; Tuesday 2026-02-03 trades although the index bar is missing, because 1,850 of the month's busiest 2,000 Flattrade series have one; Saturday 2026-01-31 does not, because only 7 series have a bar; and asking a second time sends no more queries, because the calendar keeps each exchange's days after the first read.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/calendar/TradingCalendar/example_1_trading_days_from_stored_bars.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import calendar as unified_calendar
from stock_brokers.instruments.historical.utilities.unified.calendar import (
    TradingCalendar,
)


class StandInCursor:
    """A stand-in for a psycopg2 cursor that answers the calendar's two queries.

    Attributes:
        connection (StandInConnection): The connection holding the canned rows.
        result (list): The rows the last statement produced.
    """

    def __init__(self, connection):
        """Builds a cursor over the stand-in connection.

        Args:
            connection (StandInConnection): The connection holding the canned rows.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.result = []

    def __enter__(self):
        """Opens the cursor as a context manager.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the cursor, letting any exception carry on.

        Args:
            exception_type (type | None): The class of an exception raised inside the block.
            exception (BaseException | None): The exception raised inside the block.
            traceback (types.TracebackType | None): Where it was raised.

        Returns:
            bool: Always False, so an exception is not swallowed.
        """
        return False

    def execute(self, statement, parameters):
        """Answers the benchmark index query or the Flattrade count query.

        Args:
            statement (str): The SQL text.
            parameters (tuple): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        self.connection.queries += 1
        if 'zerodha.price_history' in statement:
            self.result = self.connection.index_rows
        else:
            self.result = self.connection.count_rows

    def fetchall(self):
        """Every row the last statement produced.

        Returns:
            list: The rows.
        """
        return self.result


class StandInConnection:
    """A stand-in for a psycopg2 connection holding a fortnight of NSE rows.

    Attributes:
        index_rows (list): One (date,) row per day NIFTY 50 has a daily bar.
        count_rows (list): (date, series count) rows for Flattrade's daily bars.
        queries (int): How many statements were executed.
        closed (bool): Whether `close` has been called.
    """

    def __init__(self):
        """Fills in the rows for late January and early February 2026.

        Returns:
            None: This method returns nothing.
        """
        self.index_rows = []
        index_days = [
            datetime.date(2026, 1, 27),
            datetime.date(2026, 1, 28),
            datetime.date(2026, 1, 29),
            datetime.date(2026, 1, 30),
            datetime.date(2026, 2, 1),
            datetime.date(2026, 2, 2),
            datetime.date(2026, 2, 4),
        ]
        for day in index_days:
            row = (
                day,
            )
            self.index_rows.append(row)
        self.count_rows = [
            (
                datetime.date(2026, 1, 30),
                1990,
            ),
            (
                datetime.date(2026, 1, 31),
                7,
            ),
            (
                datetime.date(2026, 2, 2),
                2000,
            ),
            (
                datetime.date(2026, 2, 3),
                1850,
            ),
        ]
        self.queries = 0
        self.closed = False

    def cursor(self):
        """Opens a stand-in cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self)

    def close(self):
        """Marks the connection closed.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True


class StandInPostgres:
    """Hands out the stand-in connection in the place of `get_postgres`.

    Attributes:
        connection (StandInConnection): The connection handed out.
    """

    def __init__(self, connection):
        """Remembers the connection to hand out.

        Args:
            connection (StandInConnection): The connection handed out.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection

    def get_postgres(self):
        """Returns the stand-in connection.

        Returns:
            StandInConnection: The connection.
        """
        return self.connection


class TradingDaysFromStoredBarsExample:
    """Reads NSE's trading days through the stand-in connection and asks about single dates.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        calendar (TradingCalendar): The calendar being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds an empty calendar.

        Returns:
            None: This method returns nothing.
        """
        self.connection = StandInConnection()
        unified_calendar.get_postgres = StandInPostgres(self.connection).get_postgres
        self.calendar = TradingCalendar()

    def ask(self, day):
        """Prints whether NSE traded on a date.

        Args:
            day (datetime.date): The date.

        Returns:
            None: This method returns nothing.
        """
        traded = self.calendar.is_trading_day('nse', day)
        print(f"{day} ({day.strftime('%A')}): traded {traded}")

    def run(self):
        """Prints the loaded days and a few single answers.

        Returns:
            None: This method returns nothing.
        """
        days = self.calendar.trading_days('nse')
        names = []
        for day in sorted(days):
            names.append(day.isoformat())
        print(f'NSE trading days: {names}')
        print(f'Queries after the first read: {self.connection.queries}, connection closed {self.connection.closed}')
        self.ask(datetime.date(2026, 1, 31))
        self.ask(datetime.date(2026, 2, 1))
        self.ask(datetime.date(2026, 2, 3))
        self.ask(datetime.date(2026, 2, 5))
        print(f'Queries after asking again: {self.connection.queries}')
        loaded_again = TradingCalendar.load('nse')
        print(f'Calling load directly reads afresh: {len(loaded_again)} days, queries now {self.connection.queries}')


if __name__ == '__main__':
    TradingDaysFromStoredBarsExample().run()
