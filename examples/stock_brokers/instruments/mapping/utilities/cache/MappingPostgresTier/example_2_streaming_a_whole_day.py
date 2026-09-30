"""Streams a whole day's mapping out of Postgres the way the daily Redis warm does, one row at a time.

The warm that fills Redis each morning reads every mapped instrument, every broker token, every order handle, every contract size, every resolved underlying and every broker's additional attributes. Holding all of that at once would cost hundreds of megabytes, so each `stream_*` method opens its connection through `streaming_connection()`, which asks the driver to stream results with a bounded row buffer, and yields one converted row at a time.

A small stand-in replaces the SQLAlchemy engine. It holds the rows each statement would return, already in the statement's `ORDER BY` order, picks them by a fragment of the statement's text, and records the execution options each connection was given. The last part of the program uses a second stand-in engine whose `unified.underlyings` table does not exist yet, as on a database where that DDL has not been applied, and shows `read_underlyings` answering an empty dictionary rather than raising.

Notice that the streamed identities carry the mapping date the caller passed, that one token's rows arrive together, and that every streaming connection was opened with `stream_results` and a buffer of `STREAM_ROW_BUFFER` rows.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingPostgresTier/example_2_streaming_a_whole_day.py
"""

import datetime
import decimal
import types
import uuid

from sqlalchemy.exc import ProgrammingError

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingPostgresTier,
)


class StandInResult:
    """A stand-in for a SQLAlchemy result holding rows already fetched.

    Attributes:
        rows (list): The rows, in order.
    """

    def __init__(self, rows):
        """Holds the rows.

        Args:
            rows (list): The rows, in order.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __iter__(self):
        """Iterates over the rows.

        Returns:
            iterator: An iterator over the rows.
        """
        return iter(self.rows)

    def all(self):
        """Returns every row.

        Returns:
            list: The rows.
        """
        return list(self.rows)

    def scalar(self):
        """Returns the first row's single value.

        Returns:
            object: The first row, which for a scalar answer is the value itself, or None when there is no row.
        """
        if not self.rows:
            return None
        return self.rows[0]


class StandInConnection:
    """A stand-in for a SQLAlchemy connection that asks its engine for each statement's rows.

    Attributes:
        engine (StandInEngine): The engine holding the answers.
    """

    def __init__(self, engine):
        """Builds the connection.

        Args:
            engine (StandInEngine): The engine holding the answers.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine

    def __enter__(self):
        """Enters a `with` block.

        Returns:
            StandInConnection: This connection.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves a `with` block without suppressing any exception.

        Args:
            exception_type (type | None): The exception's class, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (types.TracebackType | None): The traceback, if one was raised.

        Returns:
            bool: Always False.
        """
        return False

    def execution_options(self, **options):
        """Records the execution options a caller sets and returns this connection.

        Args:
            **options (dict): The options, such as stream_results.

        Returns:
            StandInConnection: This connection.
        """
        self.engine.options.append(options)
        return self

    def execute(self, statement, parameters=None):
        """Answers one statement from the engine's rows.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement.
            parameters (dict | None): The bound parameters.

        Returns:
            StandInResult: The rows for the statement.
        """
        return self.engine.answer(str(statement), parameters)


class StandInEngine:
    """A stand-in for a SQLAlchemy engine that answers statements from rows held in memory.

    Attributes:
        answers (list): Pairs of (text fragment, rows); a statement containing the fragment gets the rows, or has the rows raised when they are an exception.
        calls (list): Pairs of (text fragment, parameters) for every statement answered.
        options (list): The execution options set on each connection.
    """

    def __init__(self):
        """Builds an engine with no answers.

        Returns:
            None: This method returns nothing.
        """
        self.answers = []
        self.calls = []
        self.options = []

    def add_answer(self, fragment, rows):
        """Adds the rows a statement containing a fragment should return.

        Args:
            fragment (str): Text that appears in the statement and nowhere in the others.
            rows (list | Exception): The rows to return, or an exception to raise.

        Returns:
            None: This method returns nothing.
        """
        self.answers.append((fragment, rows))

    def connect(self):
        """Opens a connection.

        Returns:
            StandInConnection: A new connection.
        """
        return StandInConnection(self)

    def answer(self, statement_text, parameters):
        """Finds the rows for one statement and records the call.

        Args:
            statement_text (str): The statement's SQL.
            parameters (dict | None): The bound parameters.

        Returns:
            StandInResult: The rows for the statement.

        Raises:
            ValueError: If no fragment matches the statement.
            Exception: The exception stored as the answer, when one is.
        """
        for fragment, rows in self.answers:
            if fragment in statement_text:
                self.calls.append((fragment, parameters))
                if isinstance(rows, Exception):
                    raise rows
                return StandInResult(rows)
        raise ValueError(f'No stand-in answer for statement: {statement_text}')


class StreamingAWholeDayExample:
    """Streams each kind of row the warm reads and prints what the tier yields.

    Attributes:
        engine (StandInEngine): The stand-in engine holding the day's rows.
        tier (MappingPostgresTier): The tier being shown.
        mapping_date (datetime.date): The mapping date streamed.
    """

    INFY_ID = uuid.UUID('0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05')
    NIFTY_FUTURE_ID = uuid.UUID('7c1e9b20-4d3a-4f87-a6b5-0e2d9c8f1a44')
    NIFTY_INDEX_ID = uuid.UUID('2b9d4e6f-8a1c-4e35-b7d2-5f0a3c6e9b18')

    def __init__(self):
        """Builds the engine's rows and the tier around it.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.engine = StandInEngine()
        self.engine.add_answer('m.last_seen_date', [
            self.catalogue_row(self.INFY_ID, 'nse_equities', 'INFY', None, datetime.date(2024, 1, 2)),
            self.catalogue_row(self.NIFTY_FUTURE_ID, 'nse_equity_index_futures', None, 'NIFTY', datetime.date(2026, 7, 1)),
        ])
        self.engine.add_answer('m.option_type FROM', [
            self.catalogue_row(self.INFY_ID, 'nse_equities', 'INFY', None, datetime.date(2024, 1, 2)),
            self.catalogue_row(self.NIFTY_FUTURE_ID, 'nse_equity_index_futures', None, 'NIFTY', datetime.date(2026, 7, 1)),
        ])
        self.engine.add_answer('SELECT b.broker_token, m.instrument_id', [
            types.SimpleNamespace(broker_token='13238018', instrument_id=self.NIFTY_FUTURE_ID),
            types.SimpleNamespace(broker_token='408065', instrument_id=self.INFY_ID),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.INFY_ID, 'dhan', '1594', None, '1', '0.10'),
            self.handle_row(self.INFY_ID, 'zerodha', '408065', 'INFY', '1', '0.10'),
            self.handle_row(self.NIFTY_FUTURE_ID, 'zerodha', '13238018', 'NIFTY26OCTFUT', '75', '0.10'),
        ])
        self.engine.add_answer('FROM unified.contract_sizes', [
            types.SimpleNamespace(instrument_id=self.NIFTY_FUTURE_ID, units_per_lot=decimal.Decimal('75'), status='confirmed', tradeable=True),
        ])
        self.engine.add_answer('FROM unified.underlyings', [
            types.SimpleNamespace(instrument_id=self.NIFTY_FUTURE_ID, underlying_instrument_id=self.NIFTY_INDEX_ID),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, attributes', [
            types.SimpleNamespace(instrument_id=self.INFY_ID, broker='dhan', attributes=self.dhan_attributes()),
        ])
        self.tier = MappingPostgresTier(self.engine)

    def dhan_attributes(self):
        """Builds Dhan's additional attributes for INFY, cut down to two.

        Returns:
            dict: The attributes.
        """
        return {
            'isin': 'INE009A01021',
            'series': 'EQ',
        }

    def catalogue_row(self, instrument_identifier, segment, symbol, underlying_symbol, first_seen_date):
        """Builds one row of the catalogue join, which also serves the identity stream.

        Args:
            instrument_identifier (uuid.UUID): The instrument id.
            segment (str): The exchange-prefixed segment.
            symbol (str | None): The symbol of a security.
            underlying_symbol (str | None): The underlying of a future.
            first_seen_date (datetime.date): The first date the instrument was mapped.

        Returns:
            types.SimpleNamespace: The row.
        """
        shape = 'security'
        expiry_date = None
        if underlying_symbol is not None:
            shape = 'future'
            expiry_date = datetime.date(2026, 10, 27)
        return types.SimpleNamespace(
            instrument_id=instrument_identifier,
            exchange='nse',
            segment=segment,
            shape=shape,
            symbol=symbol,
            underlying_symbol=underlying_symbol,
            expiry_date=expiry_date,
            strike_price=None,
            option_type=None,
            first_seen_date=first_seen_date,
            last_seen_date=self.mapping_date,
        )

    def handle_row(self, instrument_identifier, broker, broker_token, order_symbol, lot_size, tick_size):
        """Builds one row of `unified.broker_mappings` carrying an order handle.

        Args:
            instrument_identifier (uuid.UUID): The instrument id.
            broker (str): The broker name.
            broker_token (str): The broker's token.
            order_symbol (str | None): The symbol the broker orders by, if any.
            lot_size (str): The lot size, as text.
            tick_size (str): The tick size, as text.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_identifier,
            broker=broker,
            broker_token=broker_token,
            order_symbol=order_symbol,
            lot_size=decimal.Decimal(lot_size),
            tick_size=decimal.Decimal(tick_size),
        )

    def stream_everything(self):
        """Runs each stream and prints what it yields.

        Returns:
            None: This method returns nothing.
        """
        for identity in self.tier.stream_identities(self.mapping_date):
            print(f'stream_identities: {identity["segment"]} {identity["symbol"] or identity["underlying_symbol"]} mapped on {identity["mapping_date"]}')
        for broker_token, instrument_identifier in self.tier.stream_broker_tokens(self.mapping_date, 'zerodha'):
            print(f'stream_broker_tokens zerodha: {broker_token} -> {instrument_identifier}')
        for instrument_identifier, broker, handle in self.tier.stream_order_handles(self.mapping_date):
            print(f'stream_order_handles: {instrument_identifier} {broker} {handle}')
        for instrument_identifier, units_per_lot, status, tradeable in self.tier.stream_contract_sizes(self.mapping_date):
            print(f'stream_contract_sizes: {instrument_identifier} {units_per_lot} {status} tradeable={tradeable}')
        for instrument_identifier, underlying_identifier in self.tier.stream_underlyings(self.mapping_date):
            print(f'stream_underlyings: {instrument_identifier} is written on {underlying_identifier}')
        for instrument_identifier, broker, attributes in self.tier.stream_additional_attributes(self.mapping_date):
            print(f'stream_additional_attributes: {instrument_identifier} {broker} {attributes}')
        for identity, first_seen_date, last_seen_date in self.tier.stream_catalogue(self.mapping_date):
            print(f'stream_catalogue: {identity["instrument_id"]} seen {first_seen_date} to {last_seen_date}')

    def show_streaming_connection(self):
        """Opens one streaming connection directly and prints the options every stream used.

        Returns:
            None: This method returns nothing.
        """
        with self.tier.streaming_connection() as connection:
            print(f'streaming_connection gives a {type(connection).__name__}')
        print(f'Connections opened with streaming options: {len(self.engine.options)}')
        print(f'The options: {self.engine.options[0]}')

    def show_missing_underlyings_table(self):
        """Reads underlyings from a database where that table does not exist yet.

        Returns:
            None: This method returns nothing.
        """
        missing_table = ProgrammingError(
            'SELECT instrument_id, underlying_instrument_id FROM unified.underlyings',
            {},
            Exception('relation "unified.underlyings" does not exist'),
        )
        fresh_engine = StandInEngine()
        fresh_engine.add_answer('FROM unified.underlyings', missing_table)
        fresh_tier = MappingPostgresTier(fresh_engine)
        wanted = [
            str(self.NIFTY_FUTURE_ID),
        ]
        print(f'read_underlyings before the table exists: {fresh_tier.read_underlyings(self.mapping_date, wanted)}')

    def run(self):
        """Streams the day, shows the connection options, then the missing table.

        Returns:
            None: This method returns nothing.
        """
        print(f'Rows buffered per streaming read: {MappingPostgresTier.STREAM_ROW_BUFFER}')
        self.stream_everything()
        self.show_streaming_connection()
        self.show_missing_underlyings_table()


if __name__ == '__main__':
    StreamingAWholeDayExample().run()
