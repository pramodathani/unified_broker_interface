"""Calls `IntradayLoader`'s steps by hand: choosing where a rebuild starts, testing a gap-fill broker, and rebuilding with that broker refused.

`window_start` decides how much of an instrument's intraday history is rebuilt. It starts three days before the newest bar a changed source had already been seen, so a recently corrected window is picked up; but it rebuilds from the beginning, 1990-01-01, when any source is new, when a source's history grew backwards, or when the list holds only a placeholder for an instrument that lost its sources. The program asks it about each of those cases.

`intraday_agreement` counts, in one query, the bars on which a gap-fill broker's close is within 1% of the bars already inserted, and `insert_bars` inserts one broker's stitched bars from a start time, restricted to whole missing days for a gap-fill broker. `rebuild` combines them: here Wisdom Capital agrees on only 20 of 30 shared bars, below the 95% the loader requires, so it is refused and only Flattrade's bars are inserted.

The loader opens PostgreSQL through `get_postgres` in its constructor, which the example runner points at a closed port, so the program replaces `get_postgres` in the loader module with a stand-in returning an in-memory connection. The real stitching runs inside PostgreSQL, so the stand-in answers with recorded-looking row counts and records the parameters each statement was sent with; what the program shows is the loader's own decisions around those statements. The resolver is a stand-in and the calendar is a real `TradingCalendar` with its days filled in by hand.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/loader/IntradayLoader/example_2_window_start_and_a_refused_gap_fill.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.historical.utilities.unified import loader
from stock_brokers.instruments.historical.utilities.unified.calendar import (
    TradingCalendar,
)
from stock_brokers.instruments.historical.utilities.unified.loader import (
    IntradayLoader,
    Source,
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


class WindowStartExample:
    """Asks the intraday loader where rebuilds start, then rebuilds with a gap-fill broker it refuses.

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
            30,
            20,
        )
        self.connection = StandInConnection(agreement)
        loader.get_postgres = StandInPostgres(self.connection).get_postgres
        calendar = TradingCalendar()
        calendar.days['nse'] = set()
        calendar.days['bse'] = set()
        day = datetime.date(2026, 9, 1)
        while day <= datetime.date(2026, 9, 30):
            if day.weekday() < 5:
                calendar.days['bse'].add(day)
            day += datetime.timedelta(days=1)
        self.loader = IntradayLoader('15minute', resolver=StandInSeriesResolver(), calendar=calendar)

    def source(self, source_id, broker, series, role, earliest, changed):
        """Builds one of PIDILITIND's source rows.

        Args:
            source_id (int | None): The source row's id, or None for a placeholder.
            broker (str | None): The broker, or None for a placeholder.
            series (str | None): The broker's series identifier.
            role (str | None): "primary" or "gap_fill".
            earliest (datetime.datetime | None): The broker's earliest bar.
            changed (bool): Whether the source has changed since it was last loaded.

        Returns:
            Source: The source.
        """
        return Source(
            source_id,
            broker,
            series,
            'PIDILITIND-BSE',
            role,
            'bse',
            None,
            None,
            earliest,
            NEWEST,
            changed,
        )

    def ask(self, label, *members):
        """Prints where a rebuild of these sources would start.

        Args:
            label (str): What is special about the sources.
            *members (Source): The instrument's sources.

        Returns:
            None: This method returns nothing.
        """
        print(f'window_start, {label}: {self.loader.window_start(list(members)).isoformat()}')

    def run(self):
        """Asks about each case, tests the gap-fill broker, and rebuilds.

        Returns:
            None: This method returns nothing.
        """
        flattrade = self.source(51, 'flattrade', FLATTRADE_SERIES, 'primary', EARLIEST, True)
        wisdom = self.source(52, 'wisdom_capital', WISDOM_SERIES, 'gap_fill', EARLIEST, False)
        self.ask('one source grew forwards', flattrade, wisdom)
        self.ask('a new source', flattrade, self.source(99, 'wisdom_capital', WISDOM_SERIES, 'gap_fill', EARLIEST, True))
        grew_backwards = self.source(51, 'flattrade', FLATTRADE_SERIES, 'primary', datetime.datetime(2025, 6, 2, 9, 15, tzinfo=INDIA), True)
        self.ask('a source grew backwards', grew_backwards, wisdom)
        self.ask('only a placeholder', self.source(None, None, None, None, None, True))
        cursor = self.connection.cursor()
        gap_fill_sources = [
            wisdom,
        ]
        share, compared = self.loader.intraday_agreement(cursor, 'PIDILITIND-BSE', gap_fill_sources)
        print(f'intraday_agreement with Wisdom Capital: {share:.3f} over {compared} bars')
        start = datetime.datetime(2026, 9, 22, 15, 15, tzinfo=INDIA)
        primary_sources = [
            flattrade,
        ]
        self.loader.insert_bars(cursor, 'PIDILITIND-BSE', 'bse', primary_sources, start, whole_days_only=False)
        print(f'insert_bars by hand: {self.connection.statements[-1]}')
        self.connection.statements = []
        self.loader.counts.clear()
        members = [
            flattrade,
            wisdom,
        ]
        self.loader.rebuild('PIDILITIND-BSE', members)
        print('rebuild sent:')
        for statement in self.connection.statements:
            print(f'  {statement}')
        for name in sorted(self.loader.counts):
            print(f'{name}: {self.loader.counts[name]}')

if __name__ == '__main__':
    WindowStartExample().run()
