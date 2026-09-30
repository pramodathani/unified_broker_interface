"""Maps one day of Stoxkart rows, choosing one row wherever the file lists the same instrument more than once.

Stoxkart's file lists some instruments several times: an NSE symbol under two series, a BSE bond as a normal row plus odd-lot copies, an MCX option contract under two tokens. `StoxkartMappingAdapter.run` reads the day's rows once to pick a winning token for each of those, gathers the BSE exchange traded fund list and the NSE index names already stored, and then hands over to the shared mapping run, which reads the rows again, classifies them, and writes `unified.instruments` and `unified.broker_mappings` in one transaction. Rows that lose are filed in the uncategorised buckets rather than written over the winners.

The adapter normally talks to PostgreSQL, so this program replaces its `engine` with a stand-in. The stand-in connection answers both of Stoxkart's own queries on `stoxkart.instruments`, the narrow one for the winners and the full raw-row one, with the same six hand-written rows, answers every cross-broker query with no rows, and records every write instead of running it. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class.

Notice which tokens win: the EQ series over BE for RELIANCE, the normal-lot G series row over its GC odd-lot copy, and the higher of the two tokens for the MCX option.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/stoxkart/StoxkartMappingAdapter/example_2_mapping_one_day.py
"""

import collections
import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.stoxkart import (
    StoxkartMappingAdapter,
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
    """Maps six Stoxkart rows for one date and prints the winning tokens and what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection.
        adapter (StoxkartMappingAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('NSE', '12885', 'RELIANCE', 'RELIANCE INDUSTRIES LTD', 'BE', None, 'INE002A01018', None, None, None),
            self.raw_row('NSE', '2885', 'RELIANCE', 'RELIANCE INDUSTRIES LTD', 'EQ', None, 'INE002A01018', None, None, None),
            self.raw_row('BSE', '950002', '762GS2036', 'GOI 7.62% 2036 ODD LOT', 'GC', None, 'IN0020160019', None, None, None),
            self.raw_row('BSE', '950001', '762GS2036', 'GOI 7.62% 2036', 'G', None, 'IN0020160019', None, None, None),
            self.raw_row('MCX', '440107', 'GOLDM', 'GOLDM26NOV120000CE', None, 'OPTFUT', None, '25-11-2026', '12000000', 'CE'),
            self.raw_row('MCX', '440001', 'GOLDM', 'GOLDM26NOV120000CE', None, 'OPTFUT', None, '25-11-2026', '12000000', 'CE'),
        ]
        answers = [
            (
                'SELECT token, symbol, series, exchange, instrument_type',
                raw_rows,
            ),
            (
                'SELECT * FROM stoxkart.instruments',
                raw_rows,
            ),
        ]
        self.connection = StandInConnection(answers)
        self.adapter = StoxkartMappingAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, exchange, token, symbol, description, series, instrument_type, isin, expiry, strike, option_type):
        """Builds one raw row in the shape of `stoxkart.instruments`.

        Args:
            exchange (str): The exchange code, such as NSE, BSE or MCX.
            token (str): Stoxkart's token for the row.
            symbol (str): The `symbol` column.
            description (str): The `symbol_description` column.
            series (str | None): The exchange series, for cash rows.
            instrument_type (str | None): The instrument type, for derivatives.
            isin (str | None): The `isin_code` column.
            expiry (str | None): The expiry as `DD-MM-YYYY` text.
            strike (str | None): The strike in hundredths of a rupee.
            option_type (str | None): CE or PE for an option.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchange': exchange,
            'token': token,
            'symbol': symbol,
            'symbol_description': description,
            'series': series,
            'instrument_type': instrument_type,
            'option_type': option_type,
            'expiry_date': expiry,
            'lot_size': '1',
            'strike_price': strike,
            'isin_code': isin,
            'tick_size': '5',
            'download_date': self.mapping_date,
        }

    def run(self):
        """Maps the day and prints the winning tokens, the summary and the rows written.

        Returns:
            None: This method returns nothing.
        """
        summary = self.adapter.run(self.mapping_date)
        print(f'NSE equity winners: {sorted(self.adapter.nse_equities_winning_tokens)}')
        print(f'BSE fixed income winners: {sorted(self.adapter.bse_fixed_income_winning_tokens)}')
        print(f'MCX option winners: {sorted(self.adapter.mcx_options_winning_tokens)}')
        print(f'BSE exchange traded funds from other brokers: {sorted(self.adapter.bse_etf_symbols)}')
        print(f'Cross-broker queries that found nothing: {self.connection.unanswered_queries}')
        print(f'Summary: matched {summary["matched"]}, uncategorised {summary["uncategorised"]}, errors {summary["errors"]}')
        segments = {}
        for statement, parameters in self.connection.writes:
            if not isinstance(parameters, list):
                continue
            for row in parameters:
                if 'segment' in row:
                    segments[row['instrument_id']] = row['segment']
                else:
                    print(f'  token {row["broker_token"]} -> {segments[row["instrument_id"]]}')


if __name__ == '__main__':
    MappingOneDayExample().run()
