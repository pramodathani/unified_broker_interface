"""Maps one day of Dhan rows, gathering the BSE exchange traded fund allowlist from other brokers first.

`DhanMappingAdapter.run` first asks the other brokers' tables which BSE symbols are real exchange traded funds, then hands over to the shared mapping run, which reads Dhan's raw rows, classifies them, and writes `unified.instruments` and `unified.broker_mappings` in one transaction.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets three hand-written Dhan rows, and Flattrade's BSE fund-group query gets one row naming GOLDBEES. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice that GOLDBEES becomes a BSE exchange traded fund because Flattrade lists it, while the BSE STAR mutual fund scheme code, which no other broker confirms, is filed under `bse_uncategorised`.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/dhan/DhanMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.dhan import (
    DhanMappingAdapter,
)


class StandInResult:
    """A stand-in for an SQLAlchemy result holding a fixed set of rows.

    Attributes:
        columns (list): The column names.
        rows (list): The rows, as dictionaries.
    """

    def __init__(self, rows):
        """Holds the rows.

        Args:
            rows (list): The rows, as dictionaries that all share the same keys.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.columns = []
        if rows:
            self.columns = list(rows[0])

    def keys(self):
        """The column names, as pandas asks for them.

        Returns:
            list: The column names.
        """
        return self.columns

    def fetchall(self):
        """Every row as a plain tuple, as pandas asks for them.

        Returns:
            list: The rows as tuples in column order.
        """
        tuples = []
        for row in self.rows:
            tuples.append(tuple(row.values()))
        return tuples

    def all(self):
        """Every row as a named tuple, so a column can be read as an attribute.

        Returns:
            list: The rows as named tuples.
        """
        row_type = collections.namedtuple('StandInRow', self.columns)
        named_rows = []
        for row in self.rows:
            named_rows.append(row_type(**row))
        return named_rows


class StandInConnection(interfaces.ConnectionEventsTarget):
    """A stand-in for a PostgreSQL connection that answers queries from prepared rows and records writes.

    Attributes:
        answers (list): Pairs of (a piece of query text, the rows to answer with).
        unanswered_queries (int): How many queries matched no prepared answer and got no rows.
        writes (list): Each write statement's first words and its parameters.
    """

    def __init__(self, answers):
        """Holds the prepared answers and starts with nothing recorded.

        Args:
            answers (list): Pairs of (a piece of query text, the rows to answer with).

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers
        self.unanswered_queries = 0
        self.writes = []

    def __enter__(self):
        """Opens the connection for a `with` block.

        Returns:
            StandInConnection: This connection.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the connection at the end of a `with` block.

        Args:
            exception_type (type | None): The type of any exception raised in the block.
            exception (BaseException | None): Any exception raised in the block.
            traceback (object | None): The traceback of any exception raised in the block.

        Returns:
            bool: False, so any exception carries on.
        """
        return False

    def execute(self, statement, parameters=None):
        """Answers a query from the prepared rows, or records a write.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement to run.
            parameters (dict | list | None): Its bound parameters.

        Returns:
            StandInResult: The prepared rows whose text matches, otherwise an empty result.
        """
        sql = ' '.join(str(statement).split())
        if not sql.startswith('SELECT'):
            self.writes.append((' '.join(sql.split()[:3]), parameters))
            return StandInResult([])
        for query_text, rows in self.answers:
            if query_text in sql:
                return StandInResult(rows)
        self.unanswered_queries += 1
        return StandInResult([])


class StandInEngine:
    """A stand-in for an SQLAlchemy engine that always hands out the same stand-in connection.

    Attributes:
        connection (StandInConnection): The connection handed out.
    """

    def __init__(self, connection):
        """Holds the connection to hand out.

        Args:
            connection (StandInConnection): The connection handed out.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection

    def connect(self):
        """Hands out the connection for reading.

        Returns:
            StandInConnection: The connection.
        """
        return self.connection

    def begin(self):
        """Hands out the connection for one transaction.

        Returns:
            StandInConnection: The connection.
        """
        return self.connection


class MappingOneDayExample:
    """Maps three Dhan rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (DhanMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('2885', 'NSE', 'INE002A01018', 'RELIANCE', 'ES'),
            self.raw_row('590095', 'BSE', 'INF204KB17J3', 'GOLDBEES', 'ETF'),
            self.raw_row('176234', 'BSE', 'INF179K01XZ4', 'HDFCSTARMF', 'MF'),
        ]
        flattrade_fund_group = [
            {
                'symbol': 'GOLDBEES',
            },
        ]
        answers = [
            (
                'SELECT * FROM dhan.instruments',
                raw_rows,
            ),
            (
                'FROM flattrade.instruments WHERE download_date = :d AND exchange = \'BSE\' AND instrument = \'E\'',
                flattrade_fund_group,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = DhanMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, security_id, exchange, isin, symbol, instrument_type):
        """Builds one cash-market raw row in the shape of `dhan.instruments`.

        Args:
            security_id (str): Dhan's token for the row.
            exchange (str): The `exch_id` column.
            isin (str): The ISIN.
            symbol (str): The trading symbol.
            instrument_type (str): The `instrument_type` column.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        series = 'A'
        if exchange == 'NSE':
            series = 'EQ'
        return {
            'exch_id': exchange,
            'segment': 'E',
            'security_id': security_id,
            'isin': isin,
            'instrument': 'EQUITY',
            'underlying_symbol': symbol,
            'symbol_name': symbol,
            'display_name': symbol,
            'instrument_type': instrument_type,
            'series': series,
            'lot_size': '1.0',
            'tick_size': '5.0',
            'download_date': self.mapping_date,
        }

    def run(self):
        """Maps the day and prints the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        summary = self.adapter.run(self.mapping_date)
        print(f'BSE exchange traded funds confirmed by other brokers: {sorted(self.adapter.bse_etf_symbols)}')
        print(f'Cross-broker queries that found nothing: {self.connection.unanswered_queries}')
        print(f'Summary: matched {summary["matched"]}, uncategorised {summary["uncategorised"]}, errors {summary["errors"]}')
        for statement, parameters in self.connection.writes:
            print(statement)
            if not isinstance(parameters, list):
                continue
            for row in parameters:
                if 'segment' in row:
                    print(f'  {row["segment"]}: {row["symbol"]}')
                else:
                    print(f'  token {row["broker_token"]}: tick size {row["tick_size"]}, attributes {row["attributes"]}')


if __name__ == '__main__':
    MappingOneDayExample().run()
