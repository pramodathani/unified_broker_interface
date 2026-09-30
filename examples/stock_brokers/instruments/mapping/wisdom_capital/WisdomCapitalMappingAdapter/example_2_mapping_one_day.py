"""Maps one day of Wisdom Capital rows, where one symbol listed under two series keeps its best series.

A Wisdom Capital cash symbol can appear under two series on the same day, such as EQ and T0. Both rows get the same identity, and the shared mapping run keeps whichever it writes last. `WisdomCapitalMappingAdapter.read_raw_rows` therefore sorts the rows worst series first, so the preferred series, EQ, is written last and wins. `run` first gathers the BSE exchange traded fund and investment trust lists from the other brokers' tables, then hands over to the shared mapping run, which classifies the rows and writes `unified.instruments` and `unified.broker_mappings` in one transaction.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets four hand-written rows with the EQ row first, and Kotak's BSE investment trust query names one trust. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice that `read_raw_rows` puts the EQ row last, that the summary counts four memberships but three instruments, and that TCS is stored with the EQ row's token, 11536.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/wisdom_capital/WisdomCapitalMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.wisdom_capital import (
    WisdomCapitalMappingAdapter,
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
    """Maps four Wisdom Capital rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (WisdomCapitalMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('NSECM', '11536', 'TCS', 'EQ', 'INE467B01029'),
            self.raw_row('NSECM', '1511536', 'TCS', 'T0', 'INE467B01029'),
            self.raw_row('BSECM', '543245', 'INDIGRID', 'IF', 'INE219X23014'),
            self.raw_row('BSECM', '500325', 'RELIANCE', 'A', 'INE002A01018'),
        ]
        kotak_investment_trusts = [
            {
                'symbol': 'INDIGRID',
            },
        ]
        answers = [
            (
                'SELECT * FROM wisdom_capital.instruments',
                raw_rows,
            ),
            (
                'pexchseg = \'bse_cm\' AND pgroup = \'IF\'',
                kotak_investment_trusts,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = WisdomCapitalMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, exchange_segment, token, name, series, isin):
        """Builds one cash-market raw row in the shape of `wisdom_capital.instruments`.

        Args:
            exchange_segment (str): The `exchangesegment` column, NSECM or BSECM.
            token (str): The `exchangeinstrumentid` column.
            name (str): The `name` column, the trading symbol.
            series (str): The exchange series.
            isin (str): The ISIN.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchangesegment': exchange_segment,
            'exchangeinstrumentid': token,
            'instrumenttype': '8',
            'name': name,
            'description': f'{name}-{series}',
            'series': series,
            'ticksize': '0.1',
            'lotsize': '1',
            'displayname': name,
            'isin': isin,
            'contractexpiration': None,
            'strikeprice': None,
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
            print(f'  {raw_row["exchangesegment"]} {raw_row["name"]} series {raw_row["series"]}, token {raw_row["exchangeinstrumentid"]}')
        summary = self.adapter.run(self.mapping_date)
        print(f'BSE investment trusts from other brokers: {sorted(self.adapter.bse_trust_symbols)}')
        print(f'Cross-broker queries that found nothing: {self.connection.unanswered_queries}')
        print(f'Summary: matched {summary["matched"]}, memberships {summary["memberships"]}, instruments {summary["instruments_upserted"]}')
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
