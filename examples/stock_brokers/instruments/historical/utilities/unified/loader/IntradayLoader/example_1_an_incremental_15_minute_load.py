"""Runs an incremental 15 minute load for a BSE share, with Flattrade as the primary broker and Wisdom Capital filling whole missing days.

Intraday history is far too large to bring into Python, so `IntradayLoader` does the stitching in SQL. When it is built it copies the calendar's trading days into a temporary table and reads how far each source row had been seen. `run` then refreshes the sources as the daily loader does, and rebuilds each changed instrument only from where its sources changed: three days before the newest bar a changed source had already been seen, so a window the downloader re-fetched and corrected is picked up. The rebuild deletes the instrument's bars from that point, inserts the primary broker's bars in one statement, checks that the gap-fill broker's closes agree with them within 1% on at least 95% of the bars both have, and only then inserts the gap-fill broker's bars for whole days the primary lacks.

The loader opens PostgreSQL through `get_postgres` in its constructor, which the example runner points at a closed port, so the program replaces `get_postgres` in the loader module with a stand-in returning an in-memory connection. Because the real work happens inside PostgreSQL, the stand-in cannot compute it: it answers each statement with recorded-looking row counts, 118 bars deleted, 125 inserted from Flattrade, 121 of 125 shared bars agreeing and 25 filled from Wisdom Capital, and records the parameters each statement was sent with. What the program shows is therefore the loader's own decisions: the window start, the statements' parameters, the agreement test and the counts. The resolver is a stand-in passed to the constructor and the calendar is a real `TradingCalendar` with its days filled in by hand.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/loader/IntradayLoader/example_1_an_incremental_15_minute_load.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.historical.utilities.unified import loader
from stock_brokers.instruments.historical.utilities.unified.calendar import (
    TradingCalendar,
)
from stock_brokers.instruments.historical.utilities.unified.loader import (
    IntradayLoader,
)
from stock_brokers.instruments.historical.utilities.unified.resolution import (
    Resolution,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
FLATTRADE_SERIES = 'BSE|500331|PIDILITIND'
WISDOM_SERIES = '12|500331'
LAST_SEEN = datetime.datetime(2026, 9, 25, 15, 15, tzinfo=INDIA)
NEWEST = datetime.datetime(2026, 9, 29, 15, 15, tzinfo=INDIA)
EARLIEST = datetime.datetime(2025, 9, 1, 9, 15, tzinfo=INDIA)


class StandInSeriesResolver:
    """A stand-in for `SeriesResolver` that resolves both brokers' series to PIDILITIND on BSE."""

    def resolve(self, broker, identifiers):
        """Resolves each identifier to PIDILITIND on BSE.

        Args:
            broker (str): The broker.
            identifiers (list): The broker's series identifiers.

        Returns:
            dict: Identifier to a list holding one Resolution.
        """
        resolved = {}
        for identifier in identifiers:
            resolution = Resolution(
                identifier,
                'PIDILITIND-BSE',
                'bse',
                'bse_equities',
                'PIDILITIND',
                'broker_mapping',
                'active',
                None,
                datetime.date(2026, 8, 12),
                datetime.date(2026, 9, 29),
                None,
                None,
            )
            resolved[identifier] = [
                resolution,
            ]
        return resolved


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

    def mogrify(self, template, arguments):
        """Renders one row, as `execute_values` and the loader's series list ask a cursor to.

        Args:
            template (bytes): The row template.
            arguments (tuple): The row's values.

        Returns:
            bytes: The row's values as text, standing in for the rendered row.
        """
        self.connection.staged_rows.append(arguments)
        return str(arguments).encode()

    def execute(self, statement, parameters=None):
        """Runs one statement against the stand-in connection.

        Args:
            statement (str | bytes): The SQL text.
            parameters (tuple | list | None): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(statement, bytes):
            statement = statement.decode()
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
    """A stand-in for a psycopg2 connection that answers the intraday loader's statements with row counts.

    Attributes:
        encoding (str): The client encoding, which `execute_values` reads.
        staged_rows (list): Rows rendered by `mogrify` since the last statement.
        trading_days_copied (int): How many trading days were copied into the temporary table.
        agreement (tuple): The (bars compared, bars agreeing) the agreement query answers.
        statements (list): A short description of each statement that changes bars.
    """

    encoding = 'UTF8'

    def __init__(self, agreement):
        """Starts with nothing executed.

        Args:
            agreement (tuple): The (bars compared, bars agreeing) the agreement query answers.

        Returns:
            None: This method returns nothing.
        """
        self.staged_rows = []
        self.trading_days_copied = 0
        self.agreement = agreement
        self.statements = []

    def row(self, *columns):
        """Builds one result row.

        Args:
            *columns (object): The row's columns, in order.

        Returns:
            tuple: The row.
        """
        return columns

    def cursor(self):
        """Opens a stand-in cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self)

    def answer(self, statement, parameters):
        """Answers one of the loader's statements.

        Args:
            statement (str): The SQL text.
            parameters (tuple | list | dict | None): The statement's parameters.

        Returns:
            tuple: (rows, rows changed).
        """
        if 'unified_trading_days values' in statement:
            self.trading_days_copied += len(self.staged_rows)
            self.staged_rows = []
            return [], 0
        if 'temporary table' in statement or 'truncate' in statement:
            return [], 0
        if 'select source_id, broker_earliest_seen, broker_latest_seen' in statement:
            return [
                self.row(51, EARLIEST, LAST_SEEN),
                self.row(52, EARLIEST, LAST_SEEN),
            ], 0
        if 'from unified.price_history_sources where' in statement:
            return [
                self.row(51, 'flattrade', FLATTRADE_SERIES, 'PIDILITIND-BSE', 'active', EARLIEST, LAST_SEEN, EARLIEST, LAST_SEEN),
                self.row(52, 'wisdom_capital', WISDOM_SERIES, 'PIDILITIND-BSE', 'active', EARLIEST, LAST_SEEN, EARLIEST, LAST_SEEN),
            ], 0
        if 'price_history_progress' in statement:
            if 'flattrade.' in statement:
                return [
                    self.row(FLATTRADE_SERIES, EARLIEST, NEWEST),
                ], 0
            if 'wisdom_capital.' in statement:
                return [
                    self.row(WISDOM_SERIES, EARLIEST, NEWEST),
                ], 0
            return [], 0
        if 'insert into unified.price_history_sources' in statement:
            source_id = 52
            if parameters[0] == 'flattrade':
                source_id = 51
            return [
                self.row(source_id),
            ], 1
        if 'delete from unified.price_history' in statement:
            self.statements.append(f'delete bars of {parameters[0]} from {parameters[2].isoformat()}')
            return [], 118
        if 'select count(*), count(*) filter' in statement:
            return [
                self.agreement,
            ], 0
        if 'insert into unified.price_history' in statement:
            self.staged_rows = []
            broker = statement.split(' b\n')[0].split('from ')[-1].split('.')[0]
            self.statements.append(f"insert from {broker}: start {parameters['start'].isoformat()}, every {parameters['minutes']} minutes, exchange {parameters['exchange']}, series {parameters['series']}")
            if broker == 'flattrade':
                return [], 125
            return [], 25
        if 'update unified.price_history_sources' in statement:
            return [], 1
        raise ValueError(f'The stand-in does not know this statement: {statement[:60]}')

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """

    def rollback(self):
        """Accepts a rollback.

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


class IncrementalLoadExample:
    """Runs a 15 minute load for PIDILITIND on BSE and prints the loader's decisions.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        loader (IntradayLoader): The loader being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds the loader with a hand-filled calendar.

        Returns:
            None: This method returns nothing.
        """
        agreement = (
            125,
            121,
        )
        self.connection = StandInConnection(agreement)
        loader.get_postgres = StandInPostgres(self.connection).get_postgres
        calendar = TradingCalendar()
        calendar.days['nse'] = set()
        calendar.days['bse'] = set()
        day = datetime.date(2026, 9, 1)
        while day <= datetime.date(2026, 9, 30):
            if day.weekday() < 5:
                calendar.days['nse'].add(day)
                calendar.days['bse'].add(day)
            day += datetime.timedelta(days=1)
        self.loader = IntradayLoader('15minute', resolver=StandInSeriesResolver(), calendar=calendar)

    def run(self):
        """Runs the load and prints what was decided and sent.

        Returns:
            None: This method returns nothing.
        """
        print(f'Minutes per bar: {self.loader.minutes}; trading days copied: {self.connection.trading_days_copied}')
        for source_id, seen in self.loader.previously_seen.items():
            print(f'Source {source_id} previously seen from {seen[0].isoformat()} to {seen[1].isoformat()}')
        counts = self.loader.run()
        for statement in self.connection.statements:
            print(statement)
        for name in sorted(counts):
            print(f'{name}: {counts[name]}')

if __name__ == '__main__':
    IncrementalLoadExample().run()
