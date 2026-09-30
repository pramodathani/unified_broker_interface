"""Shows an order handle left in an older shape being refilled, and an unmapped instrument remembered as empty.

The order handle hash once held a bare broker token per broker rather than the four-field handle it holds now. A Redis still holding a value in that narrower shape must not be decoded into something the order route cannot use, so `MappingRedisTier.decode_order_handles` rejects any value that is not a dictionary of dictionaries, and `OrderHandleLookup.read_from_redis` treats the instrument as absent. The walk then falls through to Postgres and writes the full handle back over the old value.

An instrument that no broker maps on the day, such as a contract that expired yesterday, is a different case. `OrderHandleLookup.empty_entry` is an empty dictionary, so the miss is remembered in this process and the next order on it costs no query.

Two stand-ins replace the data stores: a Redis client that keeps hashes in dictionaries, into which the program writes one value in the old shape by hand, and a Postgres engine that holds the rows of the order handle statement, keeps only the instrument ids a statement asks for, and records every call. Notice the value in Redis before and after, and that the second round asks Postgres nothing.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/OrderHandleLookup/example_2_old_shapes_and_unmapped_instruments.py
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


class OldShapesExample:
    """Resolves one instrument held in an old shape and one no broker maps, twice.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        redis_tier (MappingRedisTier): The Redis tier over the stand-in.
        statistics (dict): The counters the lookup counts into.
        lookup (OrderHandleLookup): The lookup being shown.
    """

    SBIN_ID = '1d3f5b7d-9f1b-4d3f-a5b7-d9f1b3d5f746'
    EXPIRED_FUTURE_ID = '3a5c7e9a-1c3e-4a5c-b7e9-a1c3e5a7c957'

    def __init__(self):
        """Builds the stand-ins, the tiers and the lookup, and leaves an old-shaped value in Redis.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.SBIN_ID, 'shoonya', '3045', 'SBIN-EQ', '1', '0.05'),
            self.handle_row(self.SBIN_ID, 'zerodha', '779521', 'SBIN', '1', '0.05'),
        ])
        self.redis_tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.lookup = OrderHandleLookup(self.redis_tier, MappingPostgresTier(self.engine), self.statistics)
        old_shape = {
            self.SBIN_ID: '{"shoonya": "3045", "zerodha": "779521"}',
        }
        self.redis_client.hset(self.redis_tier.order_handles_key(self.mapping_date), old_shape)

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

    def stored_value(self):
        """Reads SBIN's raw value from the order handle hash.

        Returns:
            str | None: The stored JSON text.
        """
        return self.redis_client.hgetall(self.redis_tier.order_handles_key(self.mapping_date)).get(self.SBIN_ID)

    def run(self):
        """Resolves both instruments twice and prints the Redis value, the answers and the counters.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            self.SBIN_ID,
            self.EXPIRED_FUTURE_ID,
        ]
        print(f'Redis holds, in the old shape: {self.stored_value()}')
        print(f'read_from_redis finds: {self.lookup.read_from_redis(self.mapping_date, keys)}')
        answer = self.lookup.resolve(self.mapping_date, keys)
        print(f'SBIN handles: {answer[self.SBIN_ID]}')
        print(f'Expired future: {answer[self.EXPIRED_FUTURE_ID]}')
        print(f'  counters: {self.statistics}')
        print(f'Redis now holds: {self.stored_value()}')
        self.lookup.resolve(self.mapping_date, keys)
        print(f'Second round counters: {self.statistics}')
        print(f'Postgres queries: {len(self.engine.calls)}')
        print(f'empty_entry: {self.lookup.empty_entry()}')
        refilled = self.lookup.read_from_postgres(self.mapping_date, keys)
        print(f'read_from_postgres finds: {sorted(refilled)}')
        print(f'write_to_redis: {self.lookup.write_to_redis(self.mapping_date, refilled)}')


if __name__ == '__main__':
    OldShapesExample().run()
