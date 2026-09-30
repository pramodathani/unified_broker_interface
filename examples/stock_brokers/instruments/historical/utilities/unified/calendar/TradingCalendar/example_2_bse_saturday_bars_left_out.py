"""Shows the tenth-of-the-busiest-day rule on BSE, where a few series carry bars on Saturdays.

`TradingCalendar.load` counts a date for BSE when SENSEX has a Zerodha daily bar that day, or when Flattrade has daily bars for at least a tenth of the series it had on the busiest day of the same month. Through 2026 seven BSE series carry bars on Saturdays that were never sessions, and the threshold is what keeps them out. Because the threshold is taken per month, a thin month is judged against its own busiest day: in March 2020, when Flattrade's BSE history begins with only a few dozen series, a day with 8 series still counts.

`load` opens its own connection through `get_postgres`, and the example runner points PostgreSQL at a closed port, so this program replaces `get_postgres` in the calendar module with a stand-in that returns an in-memory connection. The stand-in answers the two queries with recorded-looking rows and records the parameters each was sent with, so the output shows that BSE is read through SENSEX's Zerodha token, 265, and Flattrade identifiers beginning `BSE|`. The program also shows that a calendar built by someone else can be shared: its `days` are filled once and every later question is answered from them.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/calendar/TradingCalendar/example_2_bse_saturday_bars_left_out.py
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
        self.connection.parameters.append(parameters)
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
    """A stand-in for a psycopg2 connection holding BSE rows from two months.

    Attributes:
        index_rows (list): One (date,) row per day SENSEX has a daily bar.
        count_rows (list): (date, series count) rows for Flattrade's daily bars.
        queries (int): How many statements were executed.
        parameters (list): The parameters each statement was sent with.
        closed (bool): Whether `close` has been called.
    """

    def __init__(self):
        """Fills in the rows for March 2020 and September 2026.

        Returns:
            None: This method returns nothing.
        """
        self.index_rows = []
        index_days = [
            datetime.date(2026, 9, 10),
            datetime.date(2026, 9, 11),
            datetime.date(2026, 9, 14),
        ]
        for day in index_days:
            row = (
                day,
            )
            self.index_rows.append(row)
        self.count_rows = []
        self.add_count(datetime.date(2020, 3, 2), 60)
        self.add_count(datetime.date(2020, 3, 3), 8)
        self.add_count(datetime.date(2020, 3, 7), 5)
        self.add_count(datetime.date(2026, 9, 11), 4100)
        self.add_count(datetime.date(2026, 9, 12), 7)
        self.add_count(datetime.date(2026, 9, 15), 4080)
        self.queries = 0
        self.parameters = []
        self.closed = False

    def add_count(self, day, series_count):
        """Adds one Flattrade count row.

        Args:
            day (datetime.date): The date.
            series_count (int): How many series have a daily bar that day.

        Returns:
            None: This method returns nothing.
        """
        row = (
            day,
            series_count,
        )
        self.count_rows.append(row)

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


class BseSaturdayBarsExample:
    """Reads BSE's trading days through the stand-in connection and shares the calendar.

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

    def ask(self, calendar, day):
        """Prints whether BSE traded on a date, according to one calendar.

        Args:
            calendar (TradingCalendar): The calendar to ask.
            day (datetime.date): The date.

        Returns:
            None: This method returns nothing.
        """
        traded = calendar.is_trading_day('bse', day)
        print(f"{day} ({day.strftime('%A')}): traded {traded}")

    def run(self):
        """Prints the loaded days, the query parameters and answers from a shared calendar.

        Returns:
            None: This method returns nothing.
        """
        days = self.calendar.trading_days('bse')
        names = []
        for day in sorted(days):
            names.append(day.isoformat())
        print(f'BSE trading days: {names}')
        print(f'Query parameters: {self.connection.parameters}')
        self.ask(self.calendar, datetime.date(2020, 3, 3))
        self.ask(self.calendar, datetime.date(2020, 3, 7))
        self.ask(self.calendar, datetime.date(2026, 9, 12))
        self.ask(self.calendar, datetime.date(2026, 9, 15))
        shared = TradingCalendar()
        shared.days = self.calendar.days
        self.ask(shared, datetime.date(2026, 9, 14))
        print(f'Queries sent in all: {self.connection.queries}')

if __name__ == '__main__':
    BseSaturdayBarsExample().run()
