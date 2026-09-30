"""Loads INDIAGLYCO's daily bars into the unified price history from Flattrade's EQ and BE series, filtering the bars that cannot be right.

`UnifiedLoader.run` does one interval's whole load: it finds every series with bars in each source broker's progress table, resolves each series to its instrument, records the pairing in `unified.price_history_sources`, and rebuilds every instrument one of whose sources is new or has grown. A rebuild lays the primary broker's series over each other with the most recent series on top: INDIAGLYCO traded on its EQ token until 2026-09-01 and on its BE token from that day, so both have a bar on 2026-09-01 and the BE series wins it. Bars on a day the exchange did not trade, off the day grid, or with a high below the open or close are dropped and counted, a bar already stored that no source provides any more is deleted, and each source row's watermarks are moved, all in one transaction.

The loader opens PostgreSQL through `get_postgres` in its constructor, and the example runner points PostgreSQL at a closed port, so the program replaces `get_postgres` in the loader module with a stand-in returning an in-memory connection. It answers the loader's queries with recorded-looking rows for two weeks of Flattrade bars and records every row written. The resolver and the trading calendar are passed in, as the constructor allows: a small stand-in resolver that knows both series, and a real `TradingCalendar` whose days are filled in by hand so it reads nothing. What to notice: the Saturday bar, the bar stamped at 09:15 and the bar with an impossible range are each dropped; the BE series' close of 2026-09-01 is the one kept; and the bar of 2026-08-21, which no source provides, is deleted.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/loader/UnifiedLoader/example_1_loading_daily_bars.py
"""

import datetime
import decimal
import zoneinfo

from stock_brokers.instruments.historical.utilities.unified import loader
from stock_brokers.instruments.historical.utilities.unified.calendar import (
    TradingCalendar,
)
from stock_brokers.instruments.historical.utilities.unified.loader import (
    UnifiedLoader,
)
from stock_brokers.instruments.historical.utilities.unified.resolution import (
    Resolution,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
EQ_SERIES = 'NSE|7000|INDIAGLYCO-EQ'
BE_SERIES = 'NSE|7001|INDIAGLYCO-BE'


class StandInSeriesResolver:
    """A stand-in for `SeriesResolver` that resolves INDIAGLYCO's two Flattrade series."""

    def resolve(self, broker, identifiers):
        """Resolves each identifier to INDIAGLYCO on NSE.

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
                'INDIAGLYCO-NSE',
                'nse',
                'nse_equities',
                'INDIAGLYCO',
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
        """Stages one row of a multi-row insert, as `execute_values` asks a cursor to.

        Args:
            template (bytes): The row template.
            arguments (tuple): The row's values.

        Returns:
            bytes: A placeholder for the rendered row.
        """
        self.connection.staged_rows.append(arguments)
        return b'(...)'

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
    """A stand-in for a psycopg2 connection over Flattrade's INDIAGLYCO bars.

    Attributes:
        encoding (str): The client encoding, which `execute_values` reads.
        bars (dict): Series identifier to its (time, open, high, low, close, volume, oi) rows.
        staged_rows (list): Rows staged by `mogrify` for the next insert.
        written (list): Every row inserted into the unified price history.
        deleted (list): The bar times deleted from it.
        source_updates (list): (source id, owned from, owned to) for each source row updated.
        next_source_id (int): The id the next new source row gets.
    """

    encoding = 'UTF8'

    def __init__(self):
        """Fills in the two series' bars.

        Returns:
            None: This method returns nothing.
        """
        self.bars = {
            EQ_SERIES: [],
            BE_SERIES: [],
        }
        self.staged_rows = []
        self.written = []
        self.deleted = []
        self.source_updates = []
        self.next_source_id = 11
        self.add_bar(EQ_SERIES, datetime.datetime(2026, 8, 27, tzinfo=INDIA), '480.00')
        self.add_bar(EQ_SERIES, datetime.datetime(2026, 8, 28, tzinfo=INDIA), '482.50')
        self.add_bar(EQ_SERIES, datetime.datetime(2026, 8, 29, tzinfo=INDIA), '482.50')
        self.add_bar(EQ_SERIES, datetime.datetime(2026, 8, 31, tzinfo=INDIA), '485.00')
        self.add_bar(EQ_SERIES, datetime.datetime(2026, 9, 1, tzinfo=INDIA), '484.00')
        self.add_bar(BE_SERIES, datetime.datetime(2026, 9, 1, tzinfo=INDIA), '484.20')
        self.add_bar(BE_SERIES, datetime.datetime(2026, 9, 2, tzinfo=INDIA), '242.50')
        self.add_bar(BE_SERIES, datetime.datetime(2026, 9, 3, 9, 15, tzinfo=INDIA), '243.00')
        self.add_bar(BE_SERIES, datetime.datetime(2026, 9, 3, tzinfo=INDIA), '244.00')
        self.add_bar(BE_SERIES, datetime.datetime(2026, 9, 4, tzinfo=INDIA), '0')

    def add_bar(self, series, moment, close_text):
        """Adds one daily bar whose open, high and low sit around its close.

        A close of 0 stands for a bar whose high was served below its open.

        Args:
            series (str): The series identifier.
            moment (datetime.datetime): The bar time.
            close_text (str): The close, as text so it becomes an exact Decimal.

        Returns:
            None: This method returns nothing.
        """
        close = decimal.Decimal(close_text)
        if close == 0:
            row = self.row(moment, decimal.Decimal('245.00'), decimal.Decimal('244.00'), decimal.Decimal('243.00'), decimal.Decimal('244.50'), 90000, None)
        else:
            row = self.row(moment, close - 1, close + 2, close - 3, close, 120000, None)
        self.bars[series].append(row)

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
            parameters (tuple | list | None): The statement's parameters.

        Returns:
            tuple: (rows, rows changed).
        """
        if 'from unified.price_history_sources where' in statement:
            return [], 0
        if 'price_history_progress' in statement:
            if 'flattrade.' not in statement:
                return [], 0
            return [
                self.row(EQ_SERIES, self.bars[EQ_SERIES][0][0], self.bars[EQ_SERIES][-1][0]),
                self.row(BE_SERIES, self.bars[BE_SERIES][0][0], self.bars[BE_SERIES][-1][0]),
            ], 0
        if 'insert into unified.price_history_sources' in statement:
            source_id = self.next_source_id
            self.next_source_id += 1
            return [
                self.row(source_id),
            ], 1
        if 'from flattrade.price_history' in statement:
            return self.bars[parameters[0]], 0
        if 'from unified.correction_ranges' in statement:
            return [], 0
        if 'select "time" from unified.price_history' in statement:
            return [
                self.row(datetime.datetime(2026, 8, 21, tzinfo=INDIA)),
                self.row(datetime.datetime(2026, 8, 27, tzinfo=INDIA)),
            ], 0
        if 'delete from unified.price_history' in statement:
            self.deleted.extend(parameters[2])
            return [], len(parameters[2])
        if 'insert into unified.price_history' in statement:
            self.written.extend(self.staged_rows)
            changed = len(self.staged_rows)
            self.staged_rows = []
            return [], changed
        if 'update unified.price_history_sources set' in statement:
            self.source_updates.append(self.row(parameters[6], parameters[2], parameters[3]))
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


class LoadingDailyBarsExample:
    """Runs a daily load for INDIAGLYCO and prints what was written, deleted and counted.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        loader (UnifiedLoader): The loader being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds the loader with a hand-filled calendar.

        Returns:
            None: This method returns nothing.
        """
        self.connection = StandInConnection()
        loader.get_postgres = StandInPostgres(self.connection).get_postgres
        calendar = TradingCalendar()
        calendar.days['nse'] = set()
        day = datetime.date(2026, 8, 17)
        while day <= datetime.date(2026, 9, 11):
            if day.weekday() < 5:
                calendar.days['nse'].add(day)
            day += datetime.timedelta(days=1)
        self.loader = UnifiedLoader('day', resolver=StandInSeriesResolver(), calendar=calendar)

    def run(self):
        """Runs the load and prints the outcome.

        Returns:
            None: This method returns nothing.
        """
        counts = self.loader.run()
        for name in sorted(counts):
            print(f'{name}: {counts[name]}')
        print('Rows written (time, close, source id):')
        for row in self.connection.written:
            print(f'  {row[0].date()} {row[6]} {row[9]}')
        deleted = []
        for moment in self.connection.deleted:
            deleted.append(moment.date().isoformat())
        print(f'Deleted: {deleted}')
        for source_id, owned_from, owned_to in self.connection.source_updates:
            print(f'Source {source_id} owns {owned_from.date()} to {owned_to.date()}')


if __name__ == '__main__':
    LoadingDailyBarsExample().run()
