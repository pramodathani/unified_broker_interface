"""Calls each step of `UnifiedLoader` by hand: refreshing the sources table, reading a corrected series, checking bars, and gap-filling an index from a second broker.

`run` strings the loader's steps together; this program calls them one at a time so each answer is visible.

- `refresh_sources` resolves every series in the source brokers' progress tables. A series that now resolves to a different instrument than its active source row says gets a new row, the old row is marked superseded, and the instrument it no longer feeds is returned as a placeholder so its bars are rebuilt; a series that resolves to nothing is kept in `unresolved`. `upsert_source` writes one source row and returns its id.
- `read_series` reads one source's bars and applies any confirmed correction: PIDILITIND's NSE bars before 2025-09-23 were served at half their price, and come back doubled, rounded to the paisa, with the volume untouched.
- `valid` passes or drops single bars, counting why.
- `stitch` lays one broker's series over each other, and `agreement` measures how often two brokers' closes agree on the days both have.
- `rebuild` builds NIFTY 50's bars: Zerodha is the primary and lacks 2026-09-10; Dhan agrees with Zerodha on all 22 shared days and fills that day; Flattrade's closes are 1% away and it is refused as a gap-fill broker.

The loader opens PostgreSQL through `get_postgres` in its constructor, which the example runner points at a closed port, so the program replaces `get_postgres` in the loader module with a stand-in returning an in-memory connection that answers the loader's queries with canned rows and records what is written. The resolver is a small stand-in passed to the constructor, and the calendar is a real `TradingCalendar` whose days are filled in by hand.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/loader/UnifiedLoader/example_2_each_step_by_hand.py
"""

import datetime
import decimal
import zoneinfo

from stock_brokers.instruments.historical.utilities.unified import loader
from stock_brokers.instruments.historical.utilities.unified.calendar import (
    TradingCalendar,
)
from stock_brokers.instruments.historical.utilities.unified.loader import (
    Bar,
    Source,
    UnifiedLoader,
)
from stock_brokers.instruments.historical.utilities.unified.resolution import (
    Resolution,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
MISSING_DAY = datetime.date(2026, 9, 10)
CORRECTION_DATE = datetime.datetime(2025, 9, 23, tzinfo=INDIA)


class StandInSeriesResolver:
    """A stand-in for `SeriesResolver` that resolves a renamed series to its new instrument and cannot place another."""

    def resolve(self, broker, identifiers):
        """Resolves each identifier, or reports it rejected.

        Args:
            broker (str): The broker.
            identifiers (list): The broker's series identifiers.

        Returns:
            dict: Identifier to a list holding one Resolution.
        """
        resolved = {}
        for identifier in identifiers:
            if identifier == 'NSE|9999|NEWCO-EQ':
                resolution = Resolution(
                    identifier,
                    'NEWCO-NSE',
                    'nse',
                    'nse_equities',
                    'NEWCO',
                    'broker_mapping',
                    'active',
                    None,
                    datetime.date(2026, 9, 3),
                    datetime.date(2026, 9, 29),
                    None,
                    None,
                )
            else:
                resolution = Resolution(
                    identifier,
                    None,
                    None,
                    None,
                    None,
                    None,
                    'rejected',
                    'no mapping, exchange token or symbol match',
                    None,
                    None,
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
    """A stand-in for a psycopg2 connection over a few brokers' stored bars.

    Attributes:
        encoding (str): The client encoding, which `execute_values` reads.
        bars (dict): (broker, series identifier) to its (time, open, high, low, close, volume, oi) rows.
        staged_rows (list): Rows staged by `mogrify` for the next insert.
        written (list): Every row inserted into the unified price history.
        superseded (list): The source ids marked superseded.
    """

    encoding = 'UTF8'

    def __init__(self):
        """Fills in NIFTY 50's bars at three brokers and PIDILITIND's at Flattrade.

        Returns:
            None: This method returns nothing.
        """
        self.bars = {
            ('zerodha', '256265'): [],
            ('dhan', '13|IDX_I|NIFTY'): [],
            ('flattrade', 'NSE|26000|Nifty 50'): [],
            ('flattrade', 'NSE|10575|PIDILITIND-EQ'): [],
        }
        self.staged_rows = []
        self.written = []
        self.superseded = []
        day = datetime.date(2026, 8, 31)
        position = 0
        while day <= datetime.date(2026, 9, 30):
            if day.weekday() < 5:
                moment = datetime.datetime(day.year, day.month, day.day, tzinfo=INDIA)
                close = decimal.Decimal(25000 + position * 10)
                if day != MISSING_DAY:
                    self.bars[('zerodha', '256265')].append(self.bar(moment, close))
                self.bars[('dhan', '13|IDX_I|NIFTY')].append(self.bar(moment, close))
                self.bars[('flattrade', 'NSE|26000|Nifty 50')].append(self.bar(moment, close * decimal.Decimal('1.01')))
                position += 1
            day += datetime.timedelta(days=1)
        self.bars[('flattrade', 'NSE|10575|PIDILITIND-EQ')].append(self.bar(datetime.datetime(2025, 9, 22, tzinfo=INDIA), decimal.Decimal('1519.05')))
        self.bars[('flattrade', 'NSE|10575|PIDILITIND-EQ')].append(self.bar(CORRECTION_DATE, decimal.Decimal('1523.00')))

    def bar(self, moment, close):
        """Builds one daily bar whose open, high and low sit around its close.

        Args:
            moment (datetime.datetime): The bar time.
            close (decimal.Decimal): The close.

        Returns:
            tuple: The bar's columns.
        """
        return self.row(moment, close - 5, close + 10, close - 12, close, 250000, None)

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
            return [
                self.row(7, 'flattrade', 'NSE|9999|NEWCO-EQ', 'OLDCO-NSE', 'active', None, None, None, None),
            ], 0
        if 'price_history_progress' in statement:
            if 'flattrade.' not in statement:
                return [], 0
            return [
                self.row('NSE|9999|NEWCO-EQ', datetime.datetime(2026, 9, 3, tzinfo=INDIA), datetime.datetime(2026, 9, 29, tzinfo=INDIA)),
                self.row('NSE|8888|MYSTERY-EQ', datetime.datetime(2026, 9, 3, tzinfo=INDIA), datetime.datetime(2026, 9, 29, tzinfo=INDIA)),
            ], 0
        if 'insert into unified.price_history_sources' in statement:
            return [
                self.row(31),
            ], 1
        if "set status = 'superseded'" in statement:
            self.superseded.append(parameters[0])
            return [], 1
        brokers = [
            'zerodha',
            'dhan',
            'flattrade',
        ]
        for broker in brokers:
            if f'from {broker}.price_history' in statement:
                return self.bars[(broker, parameters[0])], 0
        if 'from unified.correction_ranges' in statement:
            if parameters[1] != 'NSE|10575|PIDILITIND-EQ':
                return [], 0
            return [
                self.row(datetime.datetime(2020, 1, 1, tzinfo=INDIA), CORRECTION_DATE, decimal.Decimal('2'), decimal.Decimal('1')),
            ], 0
        if 'select "time" from unified.price_history' in statement:
            return [], 0
        if 'insert into unified.price_history' in statement:
            self.written.extend(self.staged_rows)
            changed = len(self.staged_rows)
            self.staged_rows = []
            return [], changed
        if 'update unified.price_history_sources set' in statement:
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


class EachStepByHandExample:
    """Calls the loader's steps one at a time and prints each answer.

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
        day = datetime.date(2025, 9, 1)
        while day <= datetime.date(2026, 9, 30):
            if day.weekday() < 5:
                calendar.days['nse'].add(day)
            day += datetime.timedelta(days=1)
        self.loader = UnifiedLoader('day', resolver=StandInSeriesResolver(), calendar=calendar)

    def source(self, source_id, broker, series, role):
        """Builds one of NIFTY 50's source rows.

        Args:
            source_id (int): The source row's id.
            broker (str): The broker.
            series (str): The broker's series identifier.
            role (str): "primary" or "gap_fill".

        Returns:
            Source: The source.
        """
        return Source(
            source_id,
            broker,
            series,
            'NIFTY50-NSE',
            role,
            'nse',
            None,
            None,
            datetime.datetime(2026, 8, 31, tzinfo=INDIA),
            datetime.datetime(2026, 9, 30, tzinfo=INDIA),
            True,
        )

    def check(self, label, bar):
        """Prints whether one bar passes the loader's checks.

        Args:
            label (str): What is odd about the bar.
            bar (Bar): The bar.

        Returns:
            None: This method returns nothing.
        """
        print(f'valid, {label}: {self.loader.valid(bar, "nse")}')

    def run(self):
        """Walks through each step and prints what it did.

        Returns:
            None: This method returns nothing.
        """
        sources = self.loader.refresh_sources()
        for source in sources:
            print(f'refresh_sources: {source.instrument_id} from {source.broker} {source.broker_series}, source {source.source_id}, changed {source.changed}')
        print(f'Superseded source rows: {self.connection.superseded}; unresolved: {self.loader.unresolved}')
        identifiers = [
            'NSE|9999|NEWCO-EQ',
        ]
        resolution = StandInSeriesResolver().resolve('flattrade', identifiers)['NSE|9999|NEWCO-EQ'][0]
        print(f"upsert_source returns id {self.loader.upsert_source('flattrade', 'NSE|9999|NEWCO-EQ', resolution, 'primary')}")
        corrected = Source(41, 'flattrade', 'NSE|10575|PIDILITIND-EQ', 'PIDILITIND-NSE', 'primary', 'nse', None, None, None, None, True)
        for bar in self.loader.read_series(corrected):
            print(f'read_series PIDILITIND {bar.time.date()}: close {bar.close}, high {bar.high}, volume {bar.volume}')
        moment = datetime.datetime(2026, 9, 15, tzinfo=INDIA)
        good = Bar(moment, decimal.Decimal('100'), decimal.Decimal('104'), decimal.Decimal('99'), decimal.Decimal('102'), 10, None)
        self.check('an ordinary bar', good)
        self.check('a zero close', good._replace(close=decimal.Decimal('0')))
        self.check('on a Sunday', good._replace(time=datetime.datetime(2026, 9, 13, tzinfo=INDIA)))
        self.check('stamped 09:15', good._replace(time=datetime.datetime(2026, 9, 15, 9, 15, tzinfo=INDIA)))
        self.check('high below the close', good._replace(high=decimal.Decimal('101')))
        zerodha = self.source(21, 'zerodha', '256265', 'primary')
        dhan = self.source(22, 'dhan', '13|IDX_I|NIFTY', 'gap_fill')
        flattrade = self.source(23, 'flattrade', 'NSE|26000|Nifty 50', 'gap_fill')
        primary_bars = self.loader.stitch([zerodha])
        print(f'stitch Zerodha: {len(primary_bars)} bars')
        print(f'agreement with Dhan: {self.loader.agreement(primary_bars, self.loader.stitch([dhan]))}')
        print(f'agreement with Flattrade: {self.loader.agreement(primary_bars, self.loader.stitch([flattrade]))}')
        members = [
            zerodha,
            dhan,
            flattrade,
        ]
        self.loader.rebuild('NIFTY50-NSE', members)
        filled = []
        for row in self.connection.written:
            if row[9] != 21:
                filled.append(f'{row[0].date()} from source {row[9]}')
        print(f'rebuild wrote {len(self.connection.written)} bars; filled from another broker: {filled}')
        for name in sorted(self.loader.counts):
            print(f'{name}: {self.loader.counts[name]}')

if __name__ == '__main__':
    EachStepByHandExample().run()
