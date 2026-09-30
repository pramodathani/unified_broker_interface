"""Resolves broker tokens and instrument ids through a `MappingCache`, the object a process holds for every mapping question.

A `MappingCache` is built once per process and passed down. It reads the current mapping date from Redis, and then answers five questions through three shared lookups: which instrument a broker token stands for (`identities_for_tokens`), every instrument it could stand for (`candidates_for_tokens`), what an instrument id is (`identities_for_instruments`), how each broker wants an order on it named (`order_handles_for_instruments`), and just each broker's token for it (`tokens_for_instruments`). Every answer found in Postgres is copied into Redis and into this process, and `cache_statistics()` counts which tier answered.

Two stand-ins replace the data stores, passed in through the cache's `engine` and `redis_connection` arguments. The Redis stand-in keeps strings and hashes in dictionaries and already holds today's mapping date, as it would after the morning warm. The Postgres engine stand-in holds the rows of the three statements the cache runs, keeps only the broker, tokens and instrument ids each statement asks for, and records every call.

Notice that Dhan's security id 1594 carries two instruments in this program's made-up rows: without a segment filter the first in tie-break order wins, with `nse_equities` the NSE listing wins, and `candidates_for_tokens` shows both. The id look-up afterwards is a process hit, because the token look-up already learned the identity. Tokens given as integers are treated as text, and an as-of date later than the mapping date, such as a holiday, is answered from the current mapping.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingCache/example_1_resolving_for_an_order.py
"""

import datetime
import decimal
import types
import uuid

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
)


class StandInPipeline:
    """A stand-in for a Redis pipeline that queues commands and runs them on execute.

    Attributes:
        redis_client (StandInRedis): The stand-in client the commands run against.
        queued (list): The queued commands, as (method, arguments) pairs.
    """

    def __init__(self, redis_client):
        """Builds an empty pipeline.

        Args:
            redis_client (StandInRedis): The stand-in client the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.redis_client = redis_client
        self.queued = []

    def set(self, key, value):
        """Queues a string write.

        Args:
            key (str): The key to write.
            value (str): The value to store.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.set, (key, value)))

    def hset(self, key, mapping):
        """Queues a hash write.

        Args:
            key (str): The hash to write into.
            mapping (dict): The fields to write.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.hset, (key, mapping)))

    def hmget(self, key, fields):
        """Queues a read of several hash fields.

        Args:
            key (str): The hash to read.
            fields (list): The fields to read.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.hmget, (key, fields)))

    def expire(self, key, seconds):
        """Queues an expiry.

        Args:
            key (str): The key to expire.
            seconds (int): How long the key may live.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append((self.redis_client.expire, (key, seconds)))

    def execute(self):
        """Runs every queued command in order.

        Returns:
            list: Each command's reply, in the order queued.
        """
        replies = []
        for method, arguments in self.queued:
            replies.append(method(*arguments))
        self.queued = []
        return replies


class StandInRedis:
    """A stand-in for a Redis client that keeps strings and hashes in dictionaries.

    Attributes:
        values (dict): Each key's value: a string, or a dict for a hash.
        expiries (dict): Each key's expiry in seconds, as last set.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}
        self.expiries = {}

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Ignored; the stand-in always runs commands in order.

        Returns:
            StandInPipeline: A new pipeline.
        """
        return StandInPipeline(self)

    def get(self, key):
        """Reads a string.

        Args:
            key (str): The key to read.

        Returns:
            str | None: The value, or None when the key is absent.
        """
        return self.values.get(key)

    def set(self, key, value):
        """Writes a string.

        Args:
            key (str): The key to write.
            value (str): The value to store.

        Returns:
            bool: Always True.
        """
        self.values[key] = value
        return True

    def exists(self, key):
        """Counts whether a key exists.

        Args:
            key (str): The key to test.

        Returns:
            int: 1 when the key exists, otherwise 0.
        """
        if key in self.values:
            return 1
        return 0

    def expire(self, key, seconds):
        """Records a key's expiry.

        Args:
            key (str): The key to expire.
            seconds (int): How long the key may live.

        Returns:
            bool: Always True.
        """
        self.expiries[key] = seconds
        return True

    def hset(self, key, mapping):
        """Writes fields into a hash.

        Args:
            key (str): The hash to write into.
            mapping (dict): The fields to write.

        Returns:
            int: The number of fields written.
        """
        stored = self.values.setdefault(key, {})
        stored.update(mapping)
        return len(mapping)

    def hmget(self, key, fields):
        """Reads several fields of a hash.

        Args:
            key (str): The hash to read.
            fields (list): The fields to read.

        Returns:
            list: Each field's value, or None where the field is absent.
        """
        stored = self.values.get(key, {})
        replies = []
        for field in fields:
            replies.append(stored.get(field))
        return replies

    def hgetall(self, key):
        """Reads a whole hash.

        Args:
            key (str): The hash to read.

        Returns:
            dict: The hash's fields, empty when the key is absent.
        """
        return dict(self.values.get(key, {}))


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

    Each statement's rows are narrowed the way its WHERE clause would narrow them: to the broker it names, and to the tokens or instrument ids it lists.

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
                kept = []
                for row in rows:
                    if self.keeps(row, parameters):
                        kept.append(row)
                return StandInResult(kept)
        raise ValueError(f'No stand-in answer for statement: {statement_text}')

    def keeps(self, row, parameters):
        """Says whether a row passes a statement's broker, token and instrument id filters.

        Args:
            row (types.SimpleNamespace): The row.
            parameters (dict | None): The bound parameters.

        Returns:
            bool: True when the row passes every filter the parameters carry.
        """
        if parameters is None:
            return True
        if 'broker' in parameters and row.broker != parameters['broker']:
            return False
        if 'tokens' in parameters and row.broker_token not in parameters['tokens']:
            return False
        if 'instrument_identifiers' in parameters and str(row.instrument_id) not in parameters['instrument_identifiers']:
            return False
        return True


class ResolvingForAnOrderExample:
    """Answers each of the cache's questions once and prints the answers and the counters.

    Attributes:
        mapping_date (datetime.date): The mapping date the stand-in Redis says is current.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        cache (MappingCache): The cache being shown.
    """

    INFY_NSE_ID = '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05'
    BSE_1594_ID = '6c4a2e08-1f3d-4b5a-9c7e-0d2f4a6c8e13'

    def __init__(self):
        """Builds the stand-ins and the cache.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.redis_client.set('unified:catalogue:current_date', self.mapping_date.isoformat())
        self.engine = StandInEngine()
        self.engine.add_answer('b.broker_token = ANY', [
            self.candidate_row('dhan', '1594', self.BSE_1594_ID, 'bse', 'bse_equities', 'GANESHHOU'),
            self.candidate_row('dhan', '1594', self.INFY_NSE_ID, 'nse', 'nse_equities', 'INFY'),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.INFY_NSE_ID, 'dhan', '1594', None),
            self.handle_row(self.INFY_NSE_ID, 'kotak', '1594', 'INFY-EQ'),
            self.handle_row(self.INFY_NSE_ID, 'zerodha', '408065', 'INFY'),
        ])
        self.cache = MappingCache(self.engine, MappingRedisConnection(self.redis_client))

    def candidate_row(self, broker, broker_token, instrument_identifier, exchange, segment, symbol):
        """Builds one row of the token candidate join for an equity.

        Args:
            broker (str): The broker name.
            broker_token (str): The broker's token.
            instrument_identifier (str): The instrument id.
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            symbol (str): The symbol.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker=broker,
            broker_token=broker_token,
            mapping_date=self.mapping_date,
            instrument_id=uuid.UUID(instrument_identifier),
            exchange=exchange,
            segment=segment,
            shape='security',
            symbol=symbol,
            underlying_symbol=None,
            expiry_date=None,
            strike_price=None,
            option_type=None,
        )

    def handle_row(self, instrument_identifier, broker, broker_token, order_symbol):
        """Builds one row of `unified.broker_mappings` carrying an equity's order handle.

        Args:
            instrument_identifier (str): The instrument id.
            broker (str): The broker name.
            broker_token (str): The broker's token.
            order_symbol (str | None): The symbol the broker orders by, if any.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=uuid.UUID(instrument_identifier),
            broker=broker,
            broker_token=broker_token,
            order_symbol=order_symbol,
            lot_size=decimal.Decimal('1'),
            tick_size=decimal.Decimal('0.10'),
        )

    def run(self):
        """Asks each question and prints the answer, then the counters and the queries.

        Returns:
            None: This method returns nothing.
        """
        print(f'The cache uses the engine it was given: {self.cache.engine is self.engine}')
        print(f'current_mapping_date: {self.cache.current_mapping_date()}')
        holiday = datetime.date(2026, 10, 2)
        print(f'resolves_to_current_date for {holiday}: {self.cache.resolves_to_current_date(holiday)}')
        tokens = [
            1594,
        ]
        unfiltered = self.cache.identities_for_tokens('dhan', tokens, holiday)
        print(f'identities_for_tokens, any segment: {unfiltered["1594"]["segment"]} {unfiltered["1594"]["symbol"]}')
        segments = [
            'nse_equities',
        ]
        filtered = self.cache.identities_for_tokens('dhan', tokens, self.mapping_date, segments)
        print(f'identities_for_tokens, nse_equities only: {filtered["1594"]["segment"]} {filtered["1594"]["symbol"]}')
        candidates = self.cache.candidates_for_tokens('dhan', tokens, self.mapping_date)
        for identity in candidates['1594']:
            print(f'candidates_for_tokens: {identity["segment"]} {identity["symbol"]}')
        instruments = [
            self.INFY_NSE_ID,
        ]
        identities = self.cache.identities_for_instruments(instruments, self.mapping_date)
        print(f'identities_for_instruments: {identities[self.INFY_NSE_ID]["symbol"]}')
        brokers = [
            'zerodha',
            'kotak',
        ]
        handles = self.cache.order_handles_for_instruments(instruments, self.mapping_date, brokers)
        print(f'order_handles_for_instruments, zerodha and kotak: {handles[self.INFY_NSE_ID]}')
        print(f'tokens_for_instruments, every broker: {self.cache.tokens_for_instruments(instruments, self.mapping_date)}')
        print(f'cache_statistics: {self.cache.cache_statistics()}')
        print('Postgres queries:')
        for fragment, parameters in self.engine.calls:
            print(f'  {fragment}')


if __name__ == '__main__':
    ResolvingForAnOrderExample().run()
