"""Maps one day of Fyers rows, using other brokers' lists and the already-mapped index names.

`FyersMappingAdapter.run` first gathers, from the other brokers' tables, which NSE and BSE symbols are investment trusts and which BSE symbols are exchange traded funds, and it reads the NSE index names already stored in `unified.instruments` so that its own index names can be stored under the same spelling. It then hands over to the shared mapping run, which reads Fyers' raw rows, classifies them, and writes `unified.instruments` and `unified.broker_mappings` in one transaction.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets three hand-written Fyers rows, Dhan's NSE investment trust query names EMBASSY, and the index name query returns "NIFTY IT", as if another broker had already mapped it that day. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice that Fyers' `NIFTYIT` index is stored as "NIFTY IT", the spelling another broker already stored, and that the stored broker symbol is Fyers' readable description while the order symbol is its ticker.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/fyers/FyersMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.fyers import (
    FyersMappingAdapter,
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
    """Maps three Fyers rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (FyersMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('10100000002885', 'RELIANCE INDUSTRIES LTD', '0', 'NSE:RELIANCE-EQ', 'RELIANCE', 'INE002A01018'),
            self.raw_row('10100000009383', 'EMBASSY OFFICE PARKS REIT', '0', 'NSE:EMBASSY-RR', 'EMBASSY', 'INE041025011'),
            self.raw_row('101000000026008', 'NIFTY IT', '10', 'NSE:NIFTYIT-INDEX', 'NIFTYIT', None),
        ]
        dhan_investment_trusts = [
            {
                'symbol': 'EMBASSY',
            },
        ]
        stored_index_names = [
            {
                'symbol': 'NIFTY IT',
            },
        ]
        answers = [
            (
                'SELECT * FROM fyers.instruments',
                raw_rows,
            ),
            (
                'instrument_type IN (\'InvITU\', \'REIT\')',
                dhan_investment_trusts,
            ),
            (
                'FROM unified.instruments WHERE segment = \'nse_equity_indices\'',
                stored_index_names,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = FyersMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, token, description, instrument_type, ticker, underlying_symbol, isin):
        """Builds one NSE cash-market raw row in the shape of `fyers.instruments`.

        Args:
            token (str): Fyers' token for the row.
            description (str): The readable `symbol_details` column.
            instrument_type (str): Fyers' numeric instrument type code.
            ticker (str): The `symbol_ticker` column.
            underlying_symbol (str): The `underlying_symbol` column.
            isin (str | None): The ISIN, if Fyers published one.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'fytoken': token,
            'symbol_details': description,
            'exchange_instrument_type': instrument_type,
            'minimum_lot_size': '1',
            'tick_size': '0.1',
            'isin': isin,
            'expiry_date': None,
            'symbol_ticker': ticker,
            'exchange': '10',
            'segment': '10',
            'underlying_symbol': underlying_symbol,
            'strike_price': None,
            'option_type': None,
            'download_date': self.mapping_date,
        }

    def run(self):
        """Maps the day and prints the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        summary = self.adapter.run(self.mapping_date)
        print(f'NSE investment trusts from other brokers: {sorted(self.adapter.nse_investment_trust_symbols)}')
        print(f'Index name lookup: {self.adapter.nse_index_master_lookup}')
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
                    print(f'  token {row["broker_token"]}: broker symbol {row["broker_symbol"]!r}, order symbol {row["order_symbol"]!r}')


if __name__ == '__main__':
    MappingOneDayExample().run()
