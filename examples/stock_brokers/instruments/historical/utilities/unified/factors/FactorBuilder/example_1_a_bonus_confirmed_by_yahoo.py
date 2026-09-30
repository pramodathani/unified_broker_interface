"""Builds RELIANCE's adjustment factor for its 1:1 bonus of 2024-10-28, confirmed against the event Yahoo lists.

`FactorBuilder` derives split, bonus and demerger factors for every instrument stored unadjusted. For each one it reads the raw daily closes, fetches Yahoo's history, and takes the ratio q of Yahoo's close to the raw close on every day both have. Yahoo's close is adjusted and the raw close is not, so q is 1 after the last corporate action and steps down at each one going back in time. A step that matches an event Yahoo lists is a confirmed split at the exact ratio; here q is 0.5 before the bonus and 1 from it, and Yahoo lists the bonus as a ratio of 2.0, so the builder stores a confirmed 2-for-1 factor that halves earlier prices and doubles earlier volumes. The 50% overnight fall in the raw close is explained by that factor, so it is not reported as a raw gap.

The builder's constructor opens a PostgreSQL connection through `get_postgres`, and the example runner points PostgreSQL at a closed port, so the program replaces `get_postgres` in the factors module with a stand-in that returns an in-memory connection. That connection answers the builder's queries with 34 recorded-looking raw closes for October and November 2024 and records every row written. The builder accepts its Yahoo client as an argument, so a stand-in client is passed in; it answers with closes equal to the raw ones times q, rounded to the paisa as Yahoo rounds them, and never touches the network. The program first calls `instruments` and `raw_daily` to show what the build reads, then runs `build`.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/factors/FactorBuilder/example_1_a_bonus_confirmed_by_yahoo.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import factors
from stock_brokers.instruments.historical.utilities.unified.factors import (
    FactorBuilder,
)

BONUS_DATE = datetime.date(2024, 10, 28)


class RawHistory:
    """RELIANCE's raw daily closes around its bonus, as the unified price table would hold them.

    Attributes:
        days (list): The trading dates, oldest first.
        closes (list): The raw close on each date.
    """

    def __init__(self):
        """Builds the weekdays from 2024-10-01 to 2024-11-15 with closes near 2,700 before the bonus and 1,350 from it.

        Returns:
            None: This method returns nothing.
        """
        self.days = []
        self.closes = []
        day = datetime.date(2024, 10, 1)
        position = 0
        while day <= datetime.date(2024, 11, 15):
            if day.weekday() < 5:
                wiggle = (position % 4) * 6.5
                if day < BONUS_DATE:
                    self.closes.append(2700.0 + wiggle)
                else:
                    self.closes.append(1350.0 + wiggle / 2)
                self.days.append(day)
                position += 1
            day += datetime.timedelta(days=1)


class StandInYahooClient:
    """A stand-in for `YahooClient` that answers with closes adjusted for the bonus.

    Attributes:
        raw (RawHistory): The raw history the adjusted closes are made from.
        tickers (list): Every ticker asked for.
    """

    def __init__(self, raw):
        """Remembers the raw history.

        Args:
            raw (RawHistory): The raw history the adjusted closes are made from.

        Returns:
            None: This method returns nothing.
        """
        self.raw = raw
        self.tickers = []

    def history(self, ticker):
        """Answers Yahoo's closes and listed events for a ticker.

        Args:
            ticker (str): The Yahoo ticker.

        Returns:
            tuple: (closes by date, events by date).
        """
        self.tickers.append(ticker)
        closes = {}
        for day, raw_close in zip(self.raw.days, self.raw.closes):
            if day < BONUS_DATE:
                closes[day] = round(raw_close * 0.5, 2)
            else:
                closes[day] = raw_close
        events = {
            BONUS_DATE: 2.0,
        }
        return closes, events


class StandInCursor:
    """A stand-in for a psycopg2 cursor that hands every statement to its connection.

    Attributes:
        connection (StandInConnection): The connection that answers the statements.
        result (list): The rows the last statement produced.
        rowcount (int): How many rows the last statement changed.
    """

    def __init__(self, connection):
        """Builds a cursor over the stand-in connection.

        Args:
            connection (StandInConnection): The connection that answers the statements.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.result = []
        self.rowcount = 0

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
        """Runs one statement against the stand-in connection.

        Args:
            statement (str): The SQL text.
            parameters (tuple | dict): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        self.result, self.rowcount = self.connection.answer(statement, parameters)

    def fetchone(self):
        """The first row the last statement produced.

        Returns:
            tuple | None: The row, or None when there was none.
        """
        if not self.result:
            return None
        return self.result[0]

    def fetchall(self):
        """Every row the last statement produced.

        Returns:
            list: The rows.
        """
        return self.result


class StandInConnection:
    """A stand-in for a psycopg2 connection over RELIANCE's raw history.

    Attributes:
        raw (RawHistory): The raw history the price table query returns.
        factors_written (list): Every adjustment factor row inserted.
        fetches_written (list): Every Yahoo fetch state row written.
        commits (int): How many times the builder committed.
    """

    def __init__(self, raw):
        """Starts with nothing written.

        Args:
            raw (RawHistory): The raw history the price table query returns.

        Returns:
            None: This method returns nothing.
        """
        self.raw = raw
        self.factors_written = []
        self.fetches_written = []
        self.commits = 0

    def cursor(self):
        """Opens a stand-in cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self)

    def answer(self, statement, parameters):
        """Answers one of the builder's statements.

        Args:
            statement (str): The SQL text.
            parameters (tuple | dict): The statement's parameters.

        Returns:
            tuple: (rows, rows changed).
        """
        if 'm.symbol not like' in statement:
            row = (
                'RELIANCE-NSE',
                'nse',
                'RELIANCE',
                None,
                False,
            )
            return [row], 0
        if 'close, source_id' in statement:
            rows = []
            for day, close in zip(self.raw.days, self.raw.closes):
                row = (
                    day,
                    close,
                    501,
                )
                rows.append(row)
            return rows, 0
        if "source = 'manual'" in statement and 'select ex_date' in statement:
            return [], 0
        if 'delete from' in statement:
            return [], 0
        if 'insert into unified.adjustment_factors' in statement:
            self.factors_written.append(parameters)
            return [], 1
        if 'insert into unified.yahoo_fetch_state' in statement:
            self.fetches_written.append(parameters)
            return [], 1
        raise ValueError(f'The stand-in does not know this statement: {statement[:60]}')

    def commit(self):
        """Counts a commit.

        Returns:
            None: This method returns nothing.
        """
        self.commits += 1

    def rollback(self):
        """Ends a read transaction, which the builder does before each Yahoo request.

        Returns:
            None: This method returns nothing.
        """


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


class BonusConfirmedByYahooExample:
    """Runs the factor build for RELIANCE and prints what it stored.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        yahoo (StandInYahooClient): The stand-in Yahoo client.
        builder (FactorBuilder): The builder being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds the builder with the stand-in Yahoo client.

        Returns:
            None: This method returns nothing.
        """
        raw = RawHistory()
        self.connection = StandInConnection(raw)
        factors.get_postgres = StandInPostgres(self.connection).get_postgres
        self.yahoo = StandInYahooClient(raw)
        self.builder = FactorBuilder(self.yahoo)

    def run(self):
        """Prints what the build reads, then builds and prints the stored rows.

        Returns:
            None: This method returns nothing.
        """
        print(f'Instruments to build: {self.builder.instruments()}')
        days, closes, source_ids = self.builder.raw_daily('RELIANCE-NSE')
        print(f'Raw closes: {len(days)} days from {days[0]} to {days[-1]}, {closes[0]} on the first, {closes[-1]} on the last, source {source_ids[0]}')
        counts = self.builder.build()
        print(f'Build summary: {counts}')
        print(f'Yahoo tickers asked for: {self.yahoo.tickers}')
        for row in self.connection.factors_written:
            print(f"Stored: {row['ex_date']} {row['kind']} {row['shares_after']}:{row['shares_before']} price factor {row['price_factor']} volume factor {row['volume_factor']} {row['status']} from {row['source']}")
            print(f"  evidence {row['evidence']}")
        for fetch in self.connection.fetches_written:
            print(f'Fetch state: ticker {fetch[1]} ({fetch[2]}), status {fetch[3]}, Yahoo history {fetch[5]} to {fetch[6]}, last event {fetch[7]}')
        print(f'Commits: {self.connection.commits}')


if __name__ == '__main__':
    BonusConfirmedByYahooExample().run()
