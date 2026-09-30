"""Maps one day's raw rows into the two unified tables, against a stand-in database.

`run` is what the daily mapping job calls for each broker. It reads the broker's raw rows for one date with `read_raw_rows`, classifies each row, and then, inside one transaction, deletes that broker's mappings for the date and upserts one row per instrument into `unified.instruments` and one per broker mapping into `unified.broker_mappings`. It returns a summary and prints a one-line report.

The adapter normally reads and writes PostgreSQL, so this program replaces its `engine` with a small stand-in. The stand-in connection answers the raw-row query with four hand-written rows in the shape of `dhan.instruments`, and records every other statement it is sent instead of running it. pandas only reads through something it recognises as an SQLAlchemy connectable, and it recognises one by the `ConnectionEventsTarget` base class, so the stand-in connection inherits from that class and nothing else.

The subclass uses Dhan's rules file and overrides nothing. The fourth row has a strike price that is not a number, so building its identity fails; `run` records that as an error and carries on with the other rows rather than stopping. The unmatched row is stored under its token as its symbol, and its tick size of 5.0 is kept as written, because Dhan's rules divide the tick size by 100 only in the real segments and not in the uncategorised one. The last lines show that a subclass which forgets to set `BROKER_NAME` cannot be built.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/base/BrokerMappingAdapter/example_2_mapping_one_day.py
"""

import datetime

from sqlalchemy.engine import interfaces

from stock_brokers.instruments.mapping.base import (
    BrokerMappingAdapter,
)


class DhanRulesOnlyAdapter(BrokerMappingAdapter):
    """A mapping adapter that uses Dhan's rules file and nothing but the base class's behaviour."""

    BROKER_NAME = 'dhan'


class UnnamedAdapter(BrokerMappingAdapter):
    """A mapping adapter that forgets to name its broker."""


class StandInResult:
    """A stand-in for an SQLAlchemy result holding a fixed set of rows.

    Attributes:
        columns (list): The column names.
        rows (list): The rows, as tuples in column order.
    """

    def __init__(self, columns, rows):
        """Holds the columns and rows.

        Args:
            columns (list): The column names.
            rows (list): The rows, as tuples in column order.

        Returns:
            None: This method returns nothing.
        """
        self.columns = columns
        self.rows = rows

    def keys(self):
        """The column names, as pandas asks for them.

        Returns:
            list: The column names.
        """
        return self.columns

    def fetchall(self):
        """Every row, as pandas asks for them.

        Returns:
            list: The rows.
        """
        return self.rows

    def all(self):
        """Every row, as the adapter's own queries ask for them.

        Returns:
            list: The rows.
        """
        return self.rows


class StandInConnection(interfaces.ConnectionEventsTarget):
    """A stand-in for a PostgreSQL connection that serves one raw table and records every other statement.

    Attributes:
        raw_table (str): The raw table whose rows this connection serves.
        raw_rows (list): The raw rows, as dictionaries of column values.
        statements (list): Each recorded statement's first line and its parameters.
    """

    def __init__(self, raw_table, raw_rows):
        """Holds the raw rows and starts with no statements recorded.

        Args:
            raw_table (str): The raw table whose rows this connection serves.
            raw_rows (list): The raw rows, as dictionaries of column values.

        Returns:
            None: This method returns nothing.
        """
        self.raw_table = raw_table
        self.raw_rows = raw_rows
        self.statements = []

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
        """Answers the raw-row query from the held rows and records anything else.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement to run.
            parameters (dict | list | None): Its bound parameters.

        Returns:
            StandInResult: The raw rows for the raw-row query, otherwise an empty result.
        """
        sql = ' '.join(str(statement).split())
        if sql.startswith(f'SELECT * FROM {self.raw_table} '):
            columns = list(self.raw_rows[0])
            rows = []
            for raw_row in self.raw_rows:
                values = []
                for column in columns:
                    values.append(raw_row[column])
                rows.append(tuple(values))
            return StandInResult(columns, rows)
        self.statements.append((sql, parameters))
        return StandInResult([], [])


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
    """Maps four raw rows for one date and prints what would be written.

    Attributes:
        mapping_date (datetime.date): The snapshot date being mapped.
        connection (StandInConnection): The stand-in connection holding the raw rows.
        adapter (DhanRulesOnlyAdapter): The adapter being shown, using the stand-in engine.
    """

    def __init__(self):
        """Builds the adapter and swaps its engine for the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)
        raw_rows = [
            self.raw_row('1594', 'NSE', 'E', 'EQUITY', 'ES', 'INFY', 'INFOSYS LIMITED', None, None, None),
            self.raw_row('40215', 'NSE', 'D', 'OPTIDX', 'OP', 'NIFTY', 'NIFTY-Oct2026-25000-CE', '2026-10-27', '25000.00000', 'CE'),
            self.raw_row('990001', 'NSE', 'X', 'SPREAD', 'SP', '', 'TEST SPREAD', None, None, None),
            self.raw_row('40216', 'NSE', 'D', 'OPTIDX', 'OP', 'NIFTY', 'NIFTY-Oct2026-XX-PE', '2026-10-27', 'not a number', 'PE'),
        ]
        self.connection = StandInConnection('dhan.instruments', raw_rows)
        self.adapter = DhanRulesOnlyAdapter()
        self.adapter.engine = StandInEngine(self.connection)

    def raw_row(self, security_id, exchange, segment, instrument, instrument_type, underlying_symbol, symbol_name, expiry, strike_price, option_type):
        """Builds one raw row in the shape of `dhan.instruments`.

        Args:
            security_id (str): Dhan's token for the row.
            exchange (str): The `exch_id` column.
            segment (str): Dhan's one-letter segment code.
            instrument (str): The `instrument` column.
            instrument_type (str): The `instrument_type` column.
            underlying_symbol (str): The `underlying_symbol` column.
            symbol_name (str): The `symbol_name` column.
            expiry (str | None): The `sm_expiry_date` column.
            strike_price (str | None): The `strike_price` column.
            option_type (str | None): The `option_type` column.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exch_id': exchange,
            'segment': segment,
            'security_id': security_id,
            'isin': None,
            'instrument': instrument,
            'underlying_security_id': None,
            'underlying_symbol': underlying_symbol,
            'symbol_name': symbol_name,
            'display_name': symbol_name,
            'instrument_type': instrument_type,
            'series': None,
            'lot_size': '1.0',
            'sm_expiry_date': expiry,
            'strike_price': strike_price,
            'option_type': option_type,
            'tick_size': '5.0',
            'download_date': self.mapping_date,
        }

    def short_row(self, row):
        """Shortens one written row to its filled-in columns, leaving out the dates the example already names.

        Args:
            row (dict): One row the adapter asked to insert.

        Returns:
            dict: The row's columns that hold a value, with the instrument id cut to its first eight characters.
        """
        shortened = {}
        for column, value in row.items():
            if value is None or isinstance(value, datetime.date):
                continue
            if column == 'instrument_id':
                value = value[:8]
            shortened[column] = value
        return shortened

    def run(self):
        """Reads the raw rows, maps them, and prints the summary and the statements sent.

        Returns:
            None: This method returns nothing.
        """
        raw = self.adapter.read_raw_rows(self.connection, self.mapping_date)
        print(f'read_raw_rows returned {len(raw)} rows with {len(raw.columns)} columns')
        print()
        summary = self.adapter.run(self.mapping_date)
        print()
        for key in summary:
            print(f'{key}: {summary[key]}')
        print()
        print('Statements sent inside the write transaction:')
        for sql, parameters in self.connection.statements:
            print(f'  {sql[:60]}...')
            if isinstance(parameters, list):
                for row in parameters:
                    print(f'    {self.short_row(row)}')
            else:
                print(f'    {parameters}')
        print()
        try:
            UnnamedAdapter()
        except NotImplementedError as error:
            print(f'NotImplementedError: {error}')


if __name__ == '__main__':
    MappingOneDayExample().run()
