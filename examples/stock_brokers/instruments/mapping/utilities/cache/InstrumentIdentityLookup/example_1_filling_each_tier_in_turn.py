"""Resolves instrument ids to identities through process memory, Redis and Postgres, and shows each tier filling the one above.

An `InstrumentIdentityLookup` answers the question an order path asks just before it places an order: given a unified instrument id, what are its exchange, segment, shape, symbol, expiry, strike and option type? It is one of the three subclasses of `ThreeTierLookup` in `cache.py`, and it reads the identity hash through `MappingRedisTier` and `unified.instruments` through `MappingPostgresTier`.

Two stand-ins replace the data stores. The Redis stand-in keeps hashes in dictionaries and runs a pipeline's commands when it is executed. The Postgres stand-in is an engine that holds fixed rows for the identity statement, keeps only the ids a statement asks for, and records every call. Both are real `MappingRedisTier` and `MappingPostgresTier` objects on top, so the encoding and the row conversion are the project's own.

Notice the counters. The first `resolve` is answered by Postgres and writes both identities into the Redis hash; the second is answered from this process's memory; and a second lookup, standing in for another process that shares the same Redis, is answered by Redis without a query. The dates and the strike come back as `datetime.date` and `decimal.Decimal` from every tier.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/InstrumentIdentityLookup/example_1_filling_each_tier_in_turn.py
"""

import datetime
import decimal
import types
import uuid

from stock_brokers.instruments.mapping.utilities.cache import (
    InstrumentIdentityLookup,
    MappingPostgresTier,
    MappingRedisConnection,
    MappingRedisTier,
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


class FillingEachTierExample:
    """Resolves two instrument ids cold, warm, and from a second lookup sharing Redis.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        redis_tier (MappingRedisTier): The Redis tier over the stand-in.
        postgres_tier (MappingPostgresTier): The Postgres tier over the stand-in.
        statistics (dict): The counters the lookups share.
        lookup (InstrumentIdentityLookup): The lookup being shown.
    """

    INFY_ID = '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05'
    NIFTY_OPTION_ID = '5f0c7a8e-3b1d-4c62-9e4a-2d8b7f1c0a31'

    def __init__(self):
        """Builds both stand-ins, both tiers and the lookup.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('SELECT instrument_id, exchange', [
            types.SimpleNamespace(
                instrument_id=uuid.UUID(self.INFY_ID),
                exchange='nse',
                segment='nse_equities',
                shape='security',
                symbol='INFY',
                underlying_symbol=None,
                expiry_date=None,
                strike_price=None,
                option_type=None,
            ),
            types.SimpleNamespace(
                instrument_id=uuid.UUID(self.NIFTY_OPTION_ID),
                exchange='nse',
                segment='nse_equity_index_options',
                shape='option',
                symbol=None,
                underlying_symbol='NIFTY',
                expiry_date=datetime.date(2026, 10, 6),
                strike_price=decimal.Decimal('25000.00'),
                option_type='CE',
            ),
        ])
        self.redis_tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.postgres_tier = MappingPostgresTier(self.engine)
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.lookup = InstrumentIdentityLookup(self.redis_tier, self.postgres_tier, self.statistics)

    def describe(self, identity):
        """Describes one identity in a line.

        Args:
            identity (dict): The identity.

        Returns:
            str: The description.
        """
        name = identity['symbol'] or identity['underlying_symbol']
        return f'{identity["segment"]} {name} {identity["expiry_date"]!r} {identity["strike_price"]!r} {identity["option_type"]}'

    def run(self):
        """Resolves the ids three ways, then calls each tier method directly.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            self.INFY_ID,
            self.NIFTY_OPTION_ID,
        ]
        first = self.lookup.resolve(self.mapping_date, keys)
        for key in keys:
            print(f'First resolve: {self.describe(first[key])}')
        print(f'  counters: {self.statistics}')
        print(f'  identities now in Redis: {len(self.redis_client.hgetall(self.redis_tier.identity_key(self.mapping_date)))}')
        self.lookup.resolve(self.mapping_date, keys)
        print(f'Second resolve counters: {self.statistics}')
        second_process = InstrumentIdentityLookup(self.redis_tier, self.postgres_tier, self.statistics)
        from_redis = second_process.resolve(self.mapping_date, keys)
        print(f'Second process: {self.describe(from_redis[self.NIFTY_OPTION_ID])}')
        print(f'  counters: {self.statistics}')
        print(f'Postgres queries so far: {len(self.engine.calls)}')
        option_only = [
            self.NIFTY_OPTION_ID,
        ]
        print(f'read_from_redis finds: {list(self.lookup.read_from_redis(self.mapping_date, option_only))}')
        from_postgres = self.lookup.read_from_postgres(self.mapping_date, option_only)
        print(f'read_from_postgres finds: {list(from_postgres)}')
        print(f'write_to_redis: {self.lookup.write_to_redis(self.mapping_date, from_postgres)}')
        print(f'Postgres queries so far: {len(self.engine.calls)}')


if __name__ == '__main__':
    FillingEachTierExample().run()
