"""Shows the cache refusing a past date, warming a process up front, and moving to a new mapping date after a reset.

A `MappingCache` covers only the current mapping date. A question about an earlier date, such as a backtest asking about last week, is not a hot path, so `resolves_to_current_date` answers None for it and every look-up method raises `ValueError`; the caller is expected to test first and send such questions to `resolution.py`, which queries Postgres directly.

This program starts with a Redis that has never been warmed, so `current_mapping_date` falls back to reading the latest date from Postgres. It then calls `warm`, which a process that knows its universe can use at startup: it loads the order handles of the instruments named and every token of the brokers named, so that the first real look-up is already a process hit. After that `reset` drops everything this process holds, including the counters and the remembered date, and a new date published to Redis, as the next morning's warm would do, becomes the date the cache covers.

Two stand-ins replace the data stores, passed in through the cache's `engine` and `redis_connection` arguments. The Redis stand-in keeps strings and hashes in dictionaries. The Postgres engine stand-in holds the rows of each statement the cache runs, keeps only the broker, tokens and instrument ids a statement asks for, and records every call. Notice the counters before and after the warm, and that the look-ups after it reach neither Redis nor Postgres.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingCache/example_2_past_dates_warming_and_a_new_day.py
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


class PastDatesWarmingAndANewDayExample:
    """Refuses a past date, warms the cache, then resets it and follows a new mapping date.

    Attributes:
        mapping_date (datetime.date): The latest mapping date Postgres holds.
        redis_client (StandInRedis): The Redis stand-in, never warmed at first.
        engine (StandInEngine): The Postgres stand-in.
        cache (MappingCache): The cache being shown.
    """

    INFY_NSE_ID = '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05'
    HDFCBANK_NSE_ID = '5b7d9f1b-3d5f-4b7d-9f1b-3d5f7b9d1f68'

    def __init__(self):
        """Builds the stand-ins and the cache.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('max(mapping_date)', [
            self.mapping_date,
        ])
        self.engine.add_answer('SELECT DISTINCT broker_token', [
            types.SimpleNamespace(broker='zerodha', broker_token='408065'),
            types.SimpleNamespace(broker='zerodha', broker_token='341249'),
        ])
        self.engine.add_answer('b.broker_token = ANY', [
            self.candidate_row('zerodha', '341249', self.HDFCBANK_NSE_ID, 'nse', 'nse_equities', 'HDFCBANK'),
            self.candidate_row('zerodha', '408065', self.INFY_NSE_ID, 'nse', 'nse_equities', 'INFY'),
        ])
        self.engine.add_answer('SELECT instrument_id, broker, broker_token', [
            self.handle_row(self.INFY_NSE_ID, 'fyers', 'NSE:INFY-EQ', 'NSE:INFY-EQ'),
            self.handle_row(self.INFY_NSE_ID, 'zerodha', '408065', 'INFY'),
        ])
        self.cache = MappingCache(self.engine, MappingRedisConnection(self.redis_client))

    def refuse_a_past_date(self):
        """Asks about a date before the mapping date and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        last_week = datetime.date(2026, 9, 23)
        print(f'resolves_to_current_date for {last_week}: {self.cache.resolves_to_current_date(last_week)}')
        tokens = [
            '408065',
        ]
        try:
            self.cache.identities_for_tokens('zerodha', tokens, last_week)
        except ValueError as error:
            print(f'identities_for_tokens for {last_week}: ValueError: {error}')

    def warm_up_front(self):
        """Warms the cache for one instrument and one broker, then looks both up.

        Returns:
            None: This method returns nothing.
        """
        instruments = [
            self.INFY_NSE_ID,
        ]
        brokers = [
            'zerodha',
        ]
        loaded = self.cache.warm(self.mapping_date, instruments, brokers)
        print(f'warm loaded: {loaded}')
        print(f'  statistics after the warm: {self.cache.cache_statistics()}')
        queries_before = len(self.engine.calls)
        tokens = [
            '341249',
            '408065',
        ]
        identities = self.cache.identities_for_tokens('zerodha', tokens, self.mapping_date)
        for token in tokens:
            print(f'Token {token}: {identities[token]["symbol"]}')
        print(f'Order handles for INFY: {self.cache.order_handles_for_instruments(instruments, self.mapping_date)[self.INFY_NSE_ID]}')
        print(f'  statistics after the look-ups: {self.cache.cache_statistics()}')
        print(f'  queries the look-ups sent: {len(self.engine.calls) - queries_before}')

    def move_to_a_new_day(self):
        """Resets the cache and publishes the next mapping date to Redis.

        Returns:
            None: This method returns nothing.
        """
        next_day = datetime.date(2026, 10, 1)
        self.redis_client.set('unified:catalogue:current_date', next_day.isoformat())
        print(f'Before reset, still remembered: {self.cache.current_mapping_date()}')
        self.cache.reset()
        print(f'statistics after reset: {self.cache.cache_statistics()}')
        print(f'After reset, read from Redis: {self.cache.current_mapping_date()}')
        tokens = [
            '408065',
        ]
        try:
            self.cache.candidates_for_tokens('zerodha', tokens, self.mapping_date)
        except ValueError as error:
            print(f'candidates_for_tokens for {self.mapping_date}: ValueError: {error}')

    def run(self):
        """Reads the date from Postgres, refuses a past date, warms, then moves to a new day.

        Returns:
            None: This method returns nothing.
        """
        print(f'current_mapping_date with Redis never warmed: {self.cache.current_mapping_date()}')
        self.refuse_a_past_date()
        self.warm_up_front()
        self.move_to_a_new_day()

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


if __name__ == '__main__':
    PastDatesWarmingAndANewDayExample().run()
