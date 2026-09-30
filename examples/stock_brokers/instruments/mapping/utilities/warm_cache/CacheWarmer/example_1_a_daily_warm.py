"""Warms the Redis tier of the instrument mapping cache for the latest mapping date, and clears a superseded date.

A `CacheWarmer` runs once a day after the mapping. Given no date it asks the database for the latest mapping date. `run` then writes, in order, every instrument's identity, every broker's tokens, the order handles, the contract size decisions, the resolved underlyings, the extra broker attributes and the browsing catalogue, optionally deletes the keys of every other date, and publishes the current date last, so a reader never sees a half-written day.

Both stores are stand-ins: the engine answers the warm's queries from rows held in memory, and the Redis client keeps hashes, sorted sets and plain keys in a dictionary. The real `MappingRedisConnection` wraps the stand-in client, so every key is written through the same `MappingRedisTier` the REST API reads through. No PostgreSQL or Redis is reached. The rows describe three instruments mapped on 2026-09-28, INFY on NSE and an MCX GOLD future with an option on it, and the stand-in Redis starts with one hash left over from 2026-09-27.

The run prints its own progress, including how long it took. That time changes from run to run, so the program catches the progress lines and prints `<elapsed>` in place of the number. Notice that the tokens line appears for all ten mapped brokers even though only Dhan and Zerodha have rows here, and that the 2026-09-27 hash is gone afterwards while the current date and the warm identifier are kept.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/warm_cache/CacheWarmer/example_1_a_daily_warm.py
"""

import contextlib
import datetime
import decimal
import io
import re
import types

import sqlalchemy

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisConnection,
)
from stock_brokers.instruments.mapping.utilities.warm_cache import (
    CacheWarmer,
)


class StandInPipeline:
    """A stand-in Redis pipeline that queues writes and applies them on `execute`.

    Attributes:
        redis (StandInRedis): The stand-in client the writes are applied to.
        queued (list): The queued writes, as (name, key, value) tuples.
    """

    def __init__(self, redis):
        """Starts an empty pipeline.

        Args:
            redis (StandInRedis): The stand-in client the writes are applied to.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.queued = []

    def hset(self, key, mapping):
        """Queues writing hash fields.

        Args:
            key (str): The hash.
            mapping (dict): The fields to write.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append(('hset', key, mapping))

    def zadd(self, key, mapping):
        """Queues adding sorted set members.

        Args:
            key (str): The sorted set.
            mapping (dict): The members to their scores.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append(('zadd', key, mapping))

    def set(self, key, value):
        """Queues setting a plain key.

        Args:
            key (str): The key.
            value (str): The value.

        Returns:
            None: This method returns nothing.
        """
        self.queued.append(('set', key, value))

    def expire(self, key, seconds):
        """Accepts an expiry, which this stand-in does not keep, because it depends on the wall clock.

        Args:
            key (str): The key.
            seconds (int): How long it may live.

        Returns:
            None: This method returns nothing.
        """
        return None

    def execute(self):
        """Applies every queued write to the stand-in client.

        Returns:
            list: One None per queued write.
        """
        replies = []
        for name, key, value in self.queued:
            if name == 'hset':
                self.redis.data.setdefault(key, {}).update(value)
            elif name == 'zadd':
                members = self.redis.data.setdefault(key, set())
                for member in value:
                    members.add(member)
            else:
                self.redis.data[key] = value
            replies.append(None)
        self.queued = []
        return replies


class StandInRedis:
    """A stand-in Redis client holding hashes, sorted sets and plain keys in one dictionary.

    Attributes:
        data (dict): Key to a dict for a hash, a set for a sorted set, or text for a plain key.
    """

    def __init__(self):
        """Starts with no keys.

        Returns:
            None: This method returns nothing.
        """
        self.data = {}

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Whether the real client would wrap it in MULTI and EXEC, which this stand-in ignores.

        Returns:
            StandInPipeline: A new pipeline.
        """
        return StandInPipeline(self)

    def get(self, key):
        """Reads a plain key.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when there is none.
        """
        return self.data.get(key)

    def scan_iter(self, match):
        """Yields every key matching a pattern that ends in `*`, in sorted order.

        Args:
            match (str): The pattern.

        Yields:
            str: One matching key.
        """
        prefix = match.rstrip('*')
        for key in sorted(self.data):
            if key.startswith(prefix):
                yield key

    def delete(self, key):
        """Deletes a key.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if key in self.data:
            del self.data[key]
            return 1
        return 0


class StandInResult:
    """A stand-in for a SQLAlchemy result holding fixed rows.

    Attributes:
        rows (list): The rows.
        value (object): The single value `scalar` returns.
    """

    def __init__(self, rows, value=None):
        """Holds the rows and the scalar value.

        Args:
            rows (list): The rows.
            value (object): The single value `scalar` returns.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.value = value

    def __iter__(self):
        """Iterates over the rows.

        Returns:
            iterator: An iterator over the rows.
        """
        return iter(self.rows)

    def scalar(self):
        """The single value of a one-column answer.

        Returns:
            object: The value.
        """
        return self.value


class StandInEngine:
    """A stand-in engine, acting as its own connection, that answers the warm's queries from rows in memory.

    Attributes:
        tables (dict): Table name to its rows; a table missing from here raises the error PostgreSQL gives for a missing relation.
    """

    def __init__(self, tables):
        """Holds the tables.

        Args:
            tables (dict): Table name to its rows.

        Returns:
            None: This method returns nothing.
        """
        self.tables = tables

    def connect(self):
        """Opens a connection.

        Returns:
            StandInEngine: This engine, which also acts as its own connection.
        """
        return self

    def execution_options(self, **options):
        """Accepts streaming options, which make no difference to rows already in memory.

        Args:
            **options (object): The execution options.

        Returns:
            StandInEngine: This engine.
        """
        return self

    def __enter__(self):
        """Enters the connection block.

        Returns:
            StandInEngine: This engine.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Leaves the connection block.

        Args:
            error_type (type | None): The exception type raised inside the block, if any.
            error (BaseException | None): The exception raised inside the block, if any.
            traceback (types.TracebackType | None): The traceback, if any.

        Returns:
            bool: False, so an exception is never swallowed.
        """
        return False

    def rows_of(self, table_name, statement):
        """The rows of one table, or the error PostgreSQL raises when it does not exist.

        Args:
            table_name (str): The table.
            statement (str): The statement being run, for the error.

        Returns:
            list: The rows.

        Raises:
            sqlalchemy.exc.ProgrammingError: When the table does not exist.
        """
        if table_name not in self.tables:
            missing = Exception(f'relation "{table_name}" does not exist')
            raise sqlalchemy.exc.ProgrammingError(statement, {}, missing)
        return self.tables[table_name]

    def execute(self, statement, parameters=None):
        """Answers one query from the rows in memory.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The query.
            parameters (dict | None): The query's parameters.

        Returns:
            StandInResult: The answer.
        """
        sql = str(statement)
        if sql.startswith('SELECT max(mapping_date)'):
            latest = None
            for row in self.tables['unified.instruments']:
                latest = row.mapping_date
            return StandInResult([], latest)
        if 'unified.contract_sizes' in sql:
            return StandInResult(self.rows_of('unified.contract_sizes', sql))
        if 'unified.underlyings' in sql:
            return StandInResult(self.rows_of('unified.underlyings', sql))
        if 'attributes' in sql:
            return StandInResult(self.tables['attributes'])
        if 'order_symbol' in sql:
            return StandInResult(self.tables['order_handles'])
        if sql.startswith('SELECT b.broker_token'):
            rows = []
            for row in self.tables['tokens']:
                if row.broker == parameters['broker']:
                    rows.append(row)
            return StandInResult(rows)
        return StandInResult(self.tables['unified.instruments'])


class MappedInstruments:
    """Builds the rows of three instruments mapped on 2026-09-28: INFY on NSE, and an MCX GOLD future and an option on it.

    Attributes:
        mapping_date (datetime.date): The mapping date.
    """

    def __init__(self):
        """Settles the mapping date.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 28)

    def instrument(self, instrument_id, segment, shape, symbol, underlying_symbol, expiry_date, strike_price, option_type):
        """Builds one master row, with the first and last dates it was seen.

        Args:
            instrument_id (str): The instrument id.
            segment (str): Its exchange-prefixed segment.
            shape (str): "security", "future" or "option".
            symbol (str | None): Its symbol, None for an option.
            underlying_symbol (str | None): Its underlying's symbol.
            expiry_date (datetime.date | None): Its expiry.
            strike_price (decimal.Decimal | None): Its strike.
            option_type (str | None): "CE", "PE" or None.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            exchange=segment.split('_')[0],
            segment=segment,
            shape=shape,
            symbol=symbol,
            underlying_symbol=underlying_symbol,
            expiry_date=expiry_date,
            strike_price=strike_price,
            option_type=option_type,
            first_seen_date=datetime.date(2026, 7, 1),
            last_seen_date=self.mapping_date,
            mapping_date=self.mapping_date,
        )

    def token(self, broker, broker_token, instrument_id):
        """Builds one broker token row.

        Args:
            broker (str): The broker.
            broker_token (str): Its token.
            instrument_id (str): The instrument the token points at.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker=broker,
            broker_token=broker_token,
            instrument_id=instrument_id,
        )

    def handle(self, instrument_id, broker, broker_token, order_symbol, lot_size, tick_size):
        """Builds one order handle row.

        Args:
            instrument_id (str): The instrument id.
            broker (str): The broker.
            broker_token (str): Its token.
            order_symbol (str | None): The symbol an order is sent with.
            lot_size (decimal.Decimal): The broker's lot size.
            tick_size (decimal.Decimal): The tick size.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            broker=broker,
            broker_token=broker_token,
            order_symbol=order_symbol,
            lot_size=lot_size,
            tick_size=tick_size,
        )

    def tables(self, with_decision_tables):
        """Builds every table the warm reads.

        Args:
            with_decision_tables (bool): False to leave out `unified.contract_sizes` and `unified.underlyings`, as on a database whose DDL is older.

        Returns:
            dict: Table name to its rows.
        """
        infy = 'f310e1b0-e082-5b16-808a-25f741abb9de'
        gold_future = '6a4f0d0e-1c55-5b8e-9e3a-0b7c0f1d2a31'
        gold_option = '9d2b7c4e-7a1f-5c63-8e41-3f5a6b7c8d90'
        december = datetime.date(2026, 12, 4)
        tables = {
            'unified.instruments': [
                self.instrument(infy, 'nse_equities', 'security', 'INFY', None, None, None, None),
                self.instrument(gold_future, 'mcx_commodity_futures', 'future', 'GOLD', 'GOLD', december, None, None),
                self.instrument(gold_option, 'mcx_commodity_options', 'option', None, 'GOLD', december, decimal.Decimal('120000'), 'CE'),
            ],
            'tokens': [
                self.token('dhan', '1594', infy),
                self.token('dhan', '454818', gold_future),
                self.token('zerodha', '408065', infy),
                self.token('zerodha', '123456', gold_future),
                self.token('zerodha', '123999', gold_option),
            ],
            'order_handles': [
                self.handle(infy, 'dhan', '1594', None, decimal.Decimal('1'), decimal.Decimal('0.10')),
                self.handle(infy, 'zerodha', '408065', 'INFY', decimal.Decimal('1'), decimal.Decimal('0.10')),
                self.handle(gold_future, 'zerodha', '123456', 'GOLD26DECFUT', decimal.Decimal('1'), decimal.Decimal('1')),
            ],
            'attributes': [
                types.SimpleNamespace(
                    instrument_id=infy,
                    broker='dhan',
                    attributes={
                        'isin': 'INE009A01021',
                        'series': 'EQ',
                    },
                ),
            ],
        }
        if with_decision_tables:
            tables['unified.contract_sizes'] = [
                types.SimpleNamespace(
                    instrument_id=gold_future,
                    units_per_lot=decimal.Decimal('100'),
                    status='confirmed',
                    tradeable=True,
                ),
            ]
            tables['unified.underlyings'] = [
                types.SimpleNamespace(
                    instrument_id=gold_option,
                    underlying_instrument_id=gold_future,
                ),
            ]
        return tables


class DailyWarmExample:
    """Warms the stand-in Redis from the stand-in database and prints what it holds afterwards.

    Attributes:
        redis (StandInRedis): The stand-in Redis client.
        warmer (CacheWarmer): The warmer being shown.
    """

    def __init__(self):
        """Builds the stand-ins, leaves a superseded day in Redis and builds the warmer.

        Returns:
            None: This method returns nothing.
        """
        self.redis = StandInRedis()
        self.redis.data['unified:catalogue:2026-09-27:identity'] = {
            'f310e1b0-e082-5b16-808a-25f741abb9de': '{}',
        }
        self.redis.data['unified:catalogue:current_date'] = '2026-09-27'
        engine = StandInEngine(MappedInstruments().tables(True))
        self.warmer = CacheWarmer(
            engine=engine,
            redis_connection=MappingRedisConnection(self.redis),
        )

    def warm_with_elapsed_time_hidden(self):
        """Runs the warm with clearing and prints its progress lines with the elapsed time replaced by `<elapsed>`.

        Returns:
            dict: The counts the warm returns.
        """
        progress = io.StringIO()
        with contextlib.redirect_stdout(progress):
            counts = self.warmer.run(clear=True)
        for line in progress.getvalue().splitlines():
            print(re.sub(r'after [0-9.]+ seconds', 'after <elapsed> seconds', line))
        return counts

    def run(self):
        """Runs the warm with clearing, then prints the counts and every key left in Redis.

        Returns:
            None: This method returns nothing.
        """
        print(f'Date settled from the database: {self.warmer.mapping_date}')
        counts = self.warm_with_elapsed_time_hidden()
        print(f'Counts: {counts}')
        print('Keys in Redis:')
        for key in sorted(self.redis.data):
            value = self.redis.data[key]
            if key.endswith('warm_identifier'):
                print(f'  {key}: a new random identifier')
            elif isinstance(value, str):
                print(f'  {key}: {value}')
            else:
                print(f'  {key}: {len(value)} entries')
        handles_key = 'unified:catalogue:2026-09-28:order_handles'
        print(f'INFY order handles: {self.redis.data[handles_key]["f310e1b0-e082-5b16-808a-25f741abb9de"]}')


if __name__ == '__main__':
    DailyWarmExample().run()
