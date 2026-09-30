"""Resolves an instrument to every broker's order handle, the four things an order needs to name it at that broker.

An `OrderHandleLookup` answers the question the order route asks on every order: for this unified instrument, what token, tradeable symbol, lot size and tick size does each broker want? All four come from one row of `unified.broker_mappings` per broker, so the first look-up costs one query, and every later one in the same process is a dictionary read.

Two stand-ins replace the data stores: a Redis client that keeps hashes in dictionaries, and a Postgres engine that holds the rows of the order handle statement, keeps only the instrument ids a statement asks for, and records every call. The real `MappingRedisTier` and `MappingPostgresTier` sit on top of them.

Notice that Zerodha orders a future by its trading symbol while Dhan orders it by its security id alone, so Dhan's `order_symbol` is None; that lot and tick sizes are text, so they survive being stored as JSON exactly; and that a second lookup, standing in for another gunicorn worker, gets the handles from Redis without a query.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/OrderHandleLookup/example_1_handles_for_an_order.py
"""

import datetime
import decimal
import types
import uuid

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingPostgresTier,
    MappingRedisConnection,
    MappingRedisTier,
    OrderHandleLookup,
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


class HandlesForAnOrderExample:
    """Resolves a future's order handles cold, then from a second lookup sharing Redis.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        redis_tier (MappingRedisTier): The Redis tier over the stand-in.
        postgres_tier (MappingPostgresTier): The Postgres tier over the stand-in.
        statistics (dict): The counters the lookups share.
        lookup (OrderHandleLookup): The lookup being shown.
    """

    CRUDEOIL_FUTURE_ID = '4e6a8c0e-2b4d-4f6a-8c0e-2b4d6f8a0c35'

    def __init__(self):
        """Builds the stand-ins, the tiers and the lookup.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.CRUDEOIL_FUTURE_ID, 'dhan', '467013', None, '100', '1'),
            self.handle_row(self.CRUDEOIL_FUTURE_ID, 'zerodha', '118235911', 'CRUDEOIL26OCTFUT', '100', '1'),
        ])
        self.redis_tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.postgres_tier = MappingPostgresTier(self.engine)
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.lookup = OrderHandleLookup(self.redis_tier, self.postgres_tier, self.statistics)

    def handle_row(self, instrument_identifier, broker, broker_token, order_symbol, lot_size, tick_size):
        """Builds one row of `unified.broker_mappings` carrying an order handle.

        Args:
            instrument_identifier (str): The instrument id.
            broker (str): The broker name.
            broker_token (str): The broker's token.
            order_symbol (str | None): The symbol the broker orders by, if any.
            lot_size (str): The lot size, as text.
            tick_size (str): The tick size, as text.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=uuid.UUID(instrument_identifier),
            broker=broker,
            broker_token=broker_token,
            order_symbol=order_symbol,
            lot_size=decimal.Decimal(lot_size),
            tick_size=decimal.Decimal(tick_size),
        )

    def run(self):
        """Resolves the handles twice in this process and once in another, then calls each tier method directly.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            self.CRUDEOIL_FUTURE_ID,
        ]
        handles = self.lookup.resolve(self.mapping_date, keys)
        for broker, handle in handles[self.CRUDEOIL_FUTURE_ID].items():
            print(f'{broker}: {handle}')
        print(f'  counters: {self.statistics}')
        self.lookup.resolve(self.mapping_date, keys)
        print(f'Same process again: {self.statistics}')
        other_worker = OrderHandleLookup(self.redis_tier, self.postgres_tier, self.statistics)
        other_worker.resolve(self.mapping_date, keys)
        print(f'Another worker: {self.statistics}')
        print(f'Postgres queries: {len(self.engine.calls)}')
        stored = self.redis_client.hgetall(self.redis_tier.order_handles_key(self.mapping_date))
        print(f'Stored in Redis: {stored[self.CRUDEOIL_FUTURE_ID]}')
        print(f'empty_entry: {self.lookup.empty_entry()}')
        from_redis = self.lookup.read_from_redis(self.mapping_date, keys)
        print(f'read_from_redis brokers: {sorted(from_redis[self.CRUDEOIL_FUTURE_ID])}')
        from_postgres = self.lookup.read_from_postgres(self.mapping_date, keys)
        print(f'read_from_postgres brokers: {sorted(from_postgres[self.CRUDEOIL_FUTURE_ID])}')
        print(f'write_to_redis: {self.lookup.write_to_redis(self.mapping_date, from_postgres)}')


if __name__ == '__main__':
    HandlesForAnOrderExample().run()
