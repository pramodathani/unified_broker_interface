"""Maps one day of Flattrade rows, recovering blank-exchange rows and letting the EQ series win over BE.

`FlattradeMappingAdapter.read_raw_rows` does more than fetch. It asks the database to put the rows with a blank exchange first and the EQ-series rows last, and it marks a blank-exchange row as a recovered BSE equity when Dhan or Stoxkart lists its token as a BSE equity. `run` gathers the fund, exchange traded fund and index lists from the other brokers and then hands over to the shared mapping run, which keeps the last row written for each instrument. So when a symbol is listed under both BE and EQ, the EQ row, read last, is the one stored.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets four hand-written rows, already in the order the real query's `ORDER BY` would give, and Dhan's BSE equity token query gets one token, 500325. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice that the summary counts four segment memberships but only three distinct instruments, and that the INFY instrument is stored with the EQ row's token, 1594. LIQUIDCASE is filed as a plain equity only because the stand-in's fund lists are empty; on a real day another broker's ISIN would mark it as a fund and leave it uncategorised.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/flattrade/FlattradeMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.flattrade import (
    FlattradeMappingAdapter,
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
    """Maps four Flattrade rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (FlattradeMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('', '500325', 'RELIANCE', 'RELIANCE', ''),
            self.raw_row('NSE', '26401', 'LIQUIDCASE', 'LIQUIDCASE-BE', 'BE'),
            self.raw_row('NSE', '21594', 'INFY', 'INFY-BE', 'BE'),
            self.raw_row('NSE', '1594', 'INFY', 'INFY-EQ', 'EQ'),
        ]
        dhan_bse_equity_tokens = [
            {
                'security_id': '500325',
            },
        ]
        answers = [
            (
                'SELECT * FROM flattrade.instruments',
                raw_rows,
            ),
            (
                'SELECT security_id FROM dhan.instruments',
                dhan_bse_equity_tokens,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = FlattradeMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, exchange, token, symbol, trading_symbol, instrument):
        """Builds one cash-market raw row in the shape of `flattrade.instruments`.

        Args:
            exchange (str): The exchange code, blank where Flattrade's file leaves it blank.
            token (str): Flattrade's token for the row.
            symbol (str): The `symbol` column.
            trading_symbol (str): The `tradingsymbol` column.
            instrument (str): The `instrument` column, which holds the series for cash rows.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchange': exchange,
            'token': token,
            'lotsize': '1',
            'symbol': symbol,
            'tradingsymbol': trading_symbol,
            'instrument': instrument,
            'expiry': None,
            'strike': None,
            'optiontype': None,
            'download_date': self.mapping_date,
        }

    def run(self):
        """Reads the rows, maps the day, and prints the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        raw = self.adapter.read_raw_rows(self.connection, self.mapping_date)
        print('Rows as read_raw_rows returns them:')
        for raw_row in raw.to_dict('records'):
            print(f'  {raw_row["exchange"] or "(blank)"} {raw_row["tradingsymbol"]}: recovered BSE equity {raw_row["recovered_bse_equity"]}')
        summary = self.adapter.run(self.mapping_date)
        print(f'Cross-broker queries that found nothing: {self.connection.unanswered_queries}')
        print(f'Summary: matched {summary["matched"]}, uncategorised {summary["uncategorised"]}, memberships {summary["memberships"]}, instruments {summary["instruments_upserted"]}')
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
