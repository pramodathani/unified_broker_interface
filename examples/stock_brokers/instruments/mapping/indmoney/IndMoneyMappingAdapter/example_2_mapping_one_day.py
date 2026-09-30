"""Maps one day of IND Money rows from before it published ISINs, filling the gaps from other brokers' files.

`IndMoneyMappingAdapter.run` first gathers the NSE and BSE exchange traded fund lists, builds a map from exchange security id to ISIN out of the brokers that do publish ISINs, and reads the NSE index names already stored in `unified.instruments`. It then hands over to the shared mapping run, which reads IND Money's raw rows, classifies them, and writes `unified.instruments` and `unified.broker_mappings` in one transaction.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers queries by matching a piece of their text: the raw-row query gets three hand-written IND Money rows dated 2026-08-28, when IND Money's ISIN column was still empty; Dhan's security id and ISIN query gets two pairs; and Dhan's NSE exchange traded fund query names NIFTYBEES. Every other cross-broker query gets no rows, and every write is recorded instead of run. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice that the bond is stored under the ISIN borrowed from Dhan's file, that NIFTYBEES is moved from equities to exchange traded funds, and that the liquid fund, whose borrowed ISIN is a fund ISIN, is left in `nse_uncategorised`.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/indmoney/IndMoneyMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.indmoney import (
    IndMoneyMappingAdapter,
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
    """Maps three IND Money rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (IndMoneyMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 8, 28)
        raw_rows = [
            self.raw_row('15542', 'GB', 'GS', '762GS2036'),
            self.raw_row('10576', 'ES', 'EQ', 'NIFTYBEES'),
            self.raw_row('26401', 'ES', 'EQ', 'LIQUIDCASE'),
        ]
        dhan_isins = [
            {
                'security_id': '15542',
                'isin': 'IN0020160019',
            },
            {
                'security_id': '26401',
                'isin': 'INF0R8F01034',
            },
        ]
        dhan_exchange_traded_funds = [
            {
                'symbol': 'NIFTYBEES',
            },
        ]
        answers = [
            (
                'SELECT * FROM indmoney.instruments',
                raw_rows,
            ),
            (
                'SELECT security_id, isin FROM dhan.instruments',
                dhan_isins,
            ),
            (
                'instrument_type IN (\'MF\', \'ETF\') AND series = \'EQ\'',
                dhan_exchange_traded_funds,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = IndMoneyMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, security_id, instrument_type, series, trading_symbol):
        """Builds one NSE cash-market raw row in the shape of `indmoney.instruments`, with the ISIN still empty.

        Args:
            security_id (str): IND Money's token, the exchange's security id.
            instrument_type (str): The `sem_exch_instrument_type` column.
            series (str): The exchange series.
            trading_symbol (str): The `trading_symbol` column.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exch': 'NSE',
            'segment': 'E',
            'security_id': security_id,
            'instrument_name': 'EQUITY',
            'trading_symbol': trading_symbol,
            'lot_units': '1',
            'custom_symbol': trading_symbol,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'tick_size': '1.0',
            'sem_exch_instrument_type': instrument_type,
            'series': series,
            'symbol_name': trading_symbol,
            'isin': None,
            'download_date': self.mapping_date,
        }

    def run(self):
        """Maps the day and prints the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        summary = self.adapter.run(self.mapping_date)
        print(f'Security id to ISIN map: {self.adapter.isin_by_security_id}')
        print(f'NSE exchange traded funds from other brokers: {sorted(self.adapter.nse_etf_symbols)}')
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
                    print(f'  token {row["broker_token"]}: {row["broker_symbol"]}, tick size {row["tick_size"]}')


if __name__ == '__main__':
    MappingOneDayExample().run()
