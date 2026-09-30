"""Resolves Dhan security ids to every instrument each one carries, and shares what it learns with the identity lookup.

A `TokenCandidateLookup` answers the question a market feed asks on every tick: which unified instruments does this broker token stand for? It is built for one broker, and it keeps the whole list of candidates for a token rather than a single winner, because one token can carry more than one instrument on the same day. Dhan numbers each exchange's securities separately, so in this program's made-up rows the security id 1594 is INFY on the NSE and another company on the BSE. A caller that filters by segment later picks the right one; storing only a winner would give a filtered and an unfiltered caller the same wrong answer.

The lookup also shares an `InstrumentIdentityLookup`. Every identity it reads on the way past is remembered there, so an instrument first met through a token costs nothing when it is later asked about by id.

Two stand-ins replace the data stores: a Redis client that keeps hashes in dictionaries, and a Postgres engine that holds the rows of the token statement, keeps only the broker and tokens a statement asks for, and records every call. Notice that token 1594 comes back with two candidates in tie-break order, which is by symbol and then by instrument id, that the Redis token hash stores their instrument ids joined by a comma, and that the identity lookup knows all three instruments afterwards without having been asked.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/TokenCandidateLookup/example_1_one_token_two_instruments.py
"""

import datetime
import types
import uuid

from stock_brokers.instruments.mapping.utilities.cache import (
    InstrumentIdentityLookup,
    MappingPostgresTier,
    MappingRedisConnection,
    MappingRedisTier,
    TokenCandidateLookup,
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


class OneTokenTwoInstrumentsExample:
    """Resolves two Dhan tokens, one of which carries two instruments.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        redis_tier (MappingRedisTier): The Redis tier over the stand-in.
        statistics (dict): The counters the lookups share.
        identity_lookup (InstrumentIdentityLookup): The identity store the token lookup fills.
        lookup (TokenCandidateLookup): The lookup being shown, for Dhan.
    """

    INFY_NSE_ID = '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05'
    BSE_1594_ID = '6c4a2e08-1f3d-4b5a-9c7e-0d2f4a6c8e13'
    TCS_NSE_ID = '8f2b4d6a-0c1e-4a3b-8d5f-7a9c1e3b5d24'

    def __init__(self):
        """Builds the stand-ins, the tiers and both lookups.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('b.broker_token = ANY', [
            self.candidate_row('11536', self.TCS_NSE_ID, 'nse', 'nse_equities', 'TCS'),
            self.candidate_row('1594', self.BSE_1594_ID, 'bse', 'bse_equities', 'GANESHHOU'),
            self.candidate_row('1594', self.INFY_NSE_ID, 'nse', 'nse_equities', 'INFY'),
        ])
        self.redis_tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        postgres_tier = MappingPostgresTier(self.engine)
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.identity_lookup = InstrumentIdentityLookup(self.redis_tier, postgres_tier, self.statistics)
        self.lookup = TokenCandidateLookup(self.redis_tier, postgres_tier, self.statistics, 'dhan', self.identity_lookup)

    def candidate_row(self, broker_token, instrument_identifier, exchange, segment, symbol):
        """Builds one row of the token candidate join for an equity.

        Args:
            broker_token (str): The broker's token.
            instrument_identifier (str): The instrument id.
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            symbol (str): The symbol.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            broker='dhan',
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

    def run(self):
        """Resolves the tokens, then shows what Redis and the identity lookup now hold.

        Returns:
            None: This method returns nothing.
        """
        tokens = [
            '1594',
            '11536',
        ]
        print(f'Lookup for broker: {self.lookup.broker}')
        answer = self.lookup.resolve(self.mapping_date, tokens)
        for token in tokens:
            for identity in answer[token]:
                print(f'Token {token}: {identity["segment"]} {identity["symbol"]}')
        print(f'  counters: {self.statistics}')
        stored_tokens = self.redis_client.hgetall(self.redis_tier.tokens_key(self.mapping_date, 'dhan'))
        print(f'Redis token hash: {stored_tokens}')
        instrument_identifiers = [
            self.INFY_NSE_ID,
            self.BSE_1594_ID,
            self.TCS_NSE_ID,
        ]
        for instrument_identifier in instrument_identifiers:
            print(f'Identity lookup knows {instrument_identifier}: {self.lookup.identity_lookup.known(instrument_identifier)}')
        print(f'empty_entry: {self.lookup.empty_entry()}')
        tcs_only = [
            '11536',
        ]
        from_postgres = self.lookup.read_from_postgres(self.mapping_date, tcs_only)
        print(f'read_from_postgres 11536: {from_postgres["11536"][0]["symbol"]}')
        print(f'write_to_redis: {self.lookup.write_to_redis(self.mapping_date, from_postgres)}')
        from_redis = self.lookup.read_from_redis(self.mapping_date, tcs_only)
        print(f'read_from_redis 11536: {from_redis["11536"][0]["symbol"]}')
        print(f'Postgres queries: {len(self.engine.calls)}')


if __name__ == '__main__':
    OneTokenTwoInstrumentsExample().run()
