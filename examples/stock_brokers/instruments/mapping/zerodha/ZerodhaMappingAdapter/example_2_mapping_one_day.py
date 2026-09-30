"""Maps one day of Zerodha rows, gathering every list and map it needs from the other brokers first.

`ZerodhaMappingAdapter.run` first gathers six fund, trust and bond symbol lists from the other brokers' tables, builds a map from exchange token to ISIN out of the brokers that publish ISINs, and reads the NSE index names already stored in `unified.instruments`. It then hands over to the shared mapping run, which reads Zerodha's raw rows, classifies them, and writes `unified.instruments` and `unified.broker_mappings` in one transaction.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets four hand-written Zerodha rows, and Groww's token and ISIN query knows the NSE bond. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice the summary: four raw rows give five segment memberships but only four instruments. `classify_extra` returns the equity segment for every ordinary BSE equity, including one already classified as an equity, so RELIANCE is counted twice and written once. Notice also that the uncategorised bond's broker symbol is `nan`: pandas turns the blank name into a missing number when it reads the rows, and only the bond segments fall back to the trading symbol.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/zerodha/ZerodhaMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.zerodha import (
    ZerodhaMappingAdapter,
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
    """Maps four Zerodha rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (ZerodhaMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('408065', '1594', 'INFY', 'INFOSYS', 'NSE'),
            self.raw_row('3978753', '15542', '762GS2036-GS', None, 'NSE'),
            self.raw_row('3982849', '15558', '718GS2033-GS', None, 'NSE'),
            self.raw_row('128083204', '500325', 'RELIANCE', 'RELIANCE INDUSTRIES', 'BSE'),
        ]
        groww_isins = [
            {
                'exchange_token': '15542',
                'isin': 'IN0020160019',
            },
        ]
        answers = [
            (
                'SELECT * FROM zerodha.instruments',
                raw_rows,
            ),
            (
                'SELECT exchange_token, isin FROM groww.instruments',
                groww_isins,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = ZerodhaMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, instrument_token, exchange_token, trading_symbol, name, exchange):
        """Builds one cash-market raw row in the shape of `zerodha.instruments`.

        Args:
            instrument_token (str): Zerodha's own token.
            exchange_token (str): The exchange's token for the row.
            trading_symbol (str): The `tradingsymbol` column.
            name (str | None): The `name` column, blank on many bonds.
            exchange (str): NSE or BSE, which is also the segment for cash rows.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'instrument_token': instrument_token,
            'exchange_token': exchange_token,
            'tradingsymbol': trading_symbol,
            'name': name,
            'last_price': '0',
            'expiry': None,
            'strike': '0',
            'tick_size': '0.01',
            'lot_size': '1',
            'instrument_type': 'EQ',
            'segment': exchange,
            'exchange': exchange,
            'download_date': self.mapping_date,
        }

    def run(self):
        """Maps the day and prints the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        summary = self.adapter.run(self.mapping_date)
        print(f'Token to ISIN map: {self.adapter.isin_by_token}')
        print(f'Cross-broker queries that found nothing: {self.connection.unanswered_queries}')
        print(f'Summary: raw rows {summary["raw_rows"]}, matched {summary["matched"]}, uncategorised {summary["uncategorised"]}, memberships {summary["memberships"]}, instruments {summary["instruments_upserted"]}')
        for statement, parameters in self.connection.writes:
            print(statement)
            if not isinstance(parameters, list):
                continue
            for row in parameters:
                if 'segment' in row:
                    print(f'  {row["segment"]}: {row["symbol"]}')
                else:
                    print(f'  token {row["broker_token"]}: {row["broker_symbol"]}')


if __name__ == '__main__':
    MappingOneDayExample().run()
