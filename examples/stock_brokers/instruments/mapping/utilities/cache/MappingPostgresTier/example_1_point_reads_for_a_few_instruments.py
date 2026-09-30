"""Runs the Postgres tier's point reads, the ones a cache miss falls through to, against rows held in memory.

When neither this process nor Redis holds an answer, the mapping cache asks `MappingPostgresTier`. Each of its point reads runs one statement against `unified.instruments`, `unified.broker_mappings` or `unified.underlyings` and turns the rows into the dictionaries the cache stores: an identity per instrument, a list of candidate identities per broker token, and a handle per broker per instrument.

A small stand-in replaces the SQLAlchemy engine. It holds the rows each statement would return, already in the order the statement's `ORDER BY` asks for, picks them by a fragment of the statement's text, and records the parameters each statement was sent with. That shows the real conversion code at work without a database. Notice that one Dhan security id carries two instruments, because Dhan numbers each exchange's securities separately, and both come back in tie-break order, that instrument ids come back as text although the database hands out UUID objects, and that lot and tick sizes come back as text so they survive being stored as JSON.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingPostgresTier/example_1_point_reads_for_a_few_instruments.py
"""

import datetime
import decimal
import types
import uuid

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
        answers (list): Pairs of (text fragment, rows); a statement containing the fragment gets the rows.
        calls (list): Pairs of (text fragment, parameters) for every statement answered.
    """

    def __init__(self):
        """Builds an engine with no answers.

        Returns:
            None: This method returns nothing.
        """
        self.answers = []
        self.calls = []

    def add_answer(self, fragment, rows):
        """Adds the rows a statement containing a fragment should return.

        Args:
            fragment (str): Text that appears in the statement and nowhere in the others.
            rows (list): The rows to return.

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
        """
        for fragment, rows in self.answers:
            if fragment in statement_text:
                self.calls.append((fragment, parameters))
                return StandInResult(rows)
        raise ValueError(f'No stand-in answer for statement: {statement_text}')


class PointReadsExample:
    """Runs each point read of the Postgres tier and prints what it built from the rows.

    Attributes:
        engine (StandInEngine): The stand-in engine holding the rows.
        tier (MappingPostgresTier): The tier being shown.
        mapping_date (datetime.date): The mapping date asked about.
    """

    INFY_ID = uuid.UUID('0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05')
    INFY_BSE_ID = uuid.UUID('3d5f7a9c-1e2b-4d6f-8a0c-2e4f6a8c0e11')
    NIFTY_FUTURE_ID = uuid.UUID('7c1e9b20-4d3a-4f87-a6b5-0e2d9c8f1a44')
    NIFTY_INDEX_ID = uuid.UUID('2b9d4e6f-8a1c-4e35-b7d2-5f0a3c6e9b18')

    def __init__(self):
        """Builds the engine's rows and the tier around it.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.engine = StandInEngine()
        self.engine.add_answer('max(mapping_date)', [
            self.mapping_date,
        ])
        self.engine.add_answer('b.broker_token = ANY', [
            self.token_row('1594', self.INFY_ID, 'nse', 'nse_equities'),
            self.token_row('1594', self.INFY_BSE_ID, 'bse', 'bse_equities'),
        ])
        self.engine.add_answer('SELECT instrument_id, exchange', [
            self.instrument_row(self.NIFTY_FUTURE_ID, 'nse', 'nse_equity_index_futures', 'future', None, 'NIFTY', datetime.date(2026, 10, 27)),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.NIFTY_FUTURE_ID, 'dhan', '52168', None, decimal.Decimal('75'), decimal.Decimal('0.10')),
            self.handle_row(self.NIFTY_FUTURE_ID, 'zerodha', '13238018', 'NIFTY26OCTFUT', decimal.Decimal('75'), decimal.Decimal('0.10')),
        ])
        self.engine.add_answer('SELECT DISTINCT broker_token', [
            types.SimpleNamespace(broker_token='1594'),
            types.SimpleNamespace(broker_token='13238018'),
        ])
        self.engine.add_answer('FROM unified.underlyings', [
            types.SimpleNamespace(instrument_id=self.NIFTY_FUTURE_ID, underlying_instrument_id=self.NIFTY_INDEX_ID),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, attributes', [
            types.SimpleNamespace(instrument_id=self.INFY_ID, broker='dhan', attributes=self.equity_attributes()),
            types.SimpleNamespace(instrument_id=self.INFY_ID, broker='fyers', attributes=self.equity_attributes()),
        ])
        self.tier = MappingPostgresTier(self.engine)

    def equity_attributes(self):
        """Builds the additional attributes a broker publishes for INFY, cut down to two.

        Returns:
            dict: The attributes.
        """
        return {
            'freeze_quantity': None,
            'isin': 'INE009A01021',
        }

    def instrument_row(self, instrument_identifier, exchange, segment, shape, symbol, underlying_symbol, expiry_date):
        """Builds one row of `unified.instruments` with no strike or option type.

        Args:
            instrument_identifier (uuid.UUID): The instrument id.
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            shape (str): "security", "future" or "option".
            symbol (str | None): The symbol of a security.
            underlying_symbol (str | None): The underlying of a derivative.
            expiry_date (datetime.date | None): The expiry of a derivative.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_identifier,
            exchange=exchange,
            segment=segment,
            shape=shape,
            symbol=symbol,
            underlying_symbol=underlying_symbol,
            expiry_date=expiry_date,
            strike_price=None,
            option_type=None,
        )

    def token_row(self, broker_token, instrument_identifier, exchange, segment):
        """Builds one row of the token candidate join for an equity.

        Args:
            broker_token (str): The broker's token.
            instrument_identifier (uuid.UUID): The instrument id.
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.

        Returns:
            types.SimpleNamespace: The row.
        """
        row = self.instrument_row(instrument_identifier, exchange, segment, 'security', 'INFY', None, None)
        row.broker_token = broker_token
        row.mapping_date = self.mapping_date
        return row

    def handle_row(self, instrument_identifier, broker, broker_token, order_symbol, lot_size, tick_size):
        """Builds one row of `unified.broker_mappings` carrying an order handle.

        Args:
            instrument_identifier (uuid.UUID): The instrument id.
            broker (str): The broker name.
            broker_token (str): The broker's token.
            order_symbol (str | None): The symbol the broker orders by, if any.
            lot_size (decimal.Decimal): The lot size.
            tick_size (decimal.Decimal): The tick size.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_identifier,
            broker=broker,
            broker_token=broker_token,
            order_symbol=order_symbol,
            lot_size=lot_size,
            tick_size=tick_size,
        )

    def run(self):
        """Runs each point read and prints its answer, then the parameters sent.

        Returns:
            None: This method returns nothing.
        """
        print(f'latest_mapping_date: {self.tier.latest_mapping_date()!r}')
        tokens = [
            '1594',
        ]
        candidates = self.tier.read_token_candidates(self.mapping_date, 'dhan', tokens)
        for identity in candidates['1594']:
            print(f'read_token_candidates 1594: {identity["segment"]} {identity["instrument_id"]}')
        future_text = str(self.NIFTY_FUTURE_ID)
        future_only = [
            future_text,
        ]
        identities = self.tier.read_identities(self.mapping_date, future_only)
        print(f'read_identities: {identities[future_text]}')
        handles = self.tier.read_order_handles(self.mapping_date, future_only)
        for broker, handle in handles[future_text].items():
            print(f'read_order_handles {broker}: {handle}')
        print(f'broker_tokens_on_date: {self.tier.broker_tokens_on_date(self.mapping_date, "zerodha")}')
        print(f'read_underlyings: {self.tier.read_underlyings(self.mapping_date, future_only)}')
        print(f'read_underlyings of nothing: {self.tier.read_underlyings(self.mapping_date, [])}')
        infy_only = [
            str(self.INFY_ID),
        ]
        print(f'read_additional_attributes: {self.tier.read_additional_attributes(self.mapping_date, infy_only)}')
        row = self.handle_row(self.NIFTY_FUTURE_ID, 'kotak', '35012', 'NIFTY26OCTFUT', decimal.Decimal('75'), None)
        print(f'handle_from_row with no tick size: {self.tier.handle_from_row(row)}')
        row = self.instrument_row(self.NIFTY_INDEX_ID, 'nse', 'nse_equity_indices', 'security', 'NIFTY 50', None, None)
        print(f'identity_from_row: {self.tier.identity_from_row(row, self.mapping_date)}')
        print('Statements sent, with their parameters:')
        for fragment, parameters in self.engine.calls:
            print(f'  {fragment}: {parameters}')


if __name__ == '__main__':
    PointReadsExample().run()
