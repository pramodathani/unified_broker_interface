"""Reads tokens that an earlier process left in Redis, and remembers a token no instrument carries.

This is what a second process sees after the first has done the work. The program first writes two Dhan tokens and their identities into Redis through `MappingRedisTier.write_token_candidates`, as the daily warm or an earlier process would, and then deletes one of the identities from the Redis identity hash to imitate an entry that expired early. A fresh `TokenCandidateLookup` then resolves both tokens and a third token that Dhan does not carry at all.

Its `read_from_redis` reads the token hash, fetches only the identities the shared identity lookup does not already hold, and returns a token only when every one of its candidates was found, because a token missing a candidate could silently give a segment-filtered caller the wrong instrument. So the token with a missing identity falls through to Postgres and is refilled, while the complete one is a Redis hit. The unknown token is remembered as an empty list, its `empty_entry`, so asking about it again costs nothing.

Two stand-ins replace the data stores: a Redis client that keeps hashes in dictionaries, and a Postgres engine that holds the rows of the token statement, keeps only the broker and tokens a statement asks for, and records every call. Notice which tokens reached Postgres, and that the second round is answered entirely from this process.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/TokenCandidateLookup/example_2_reading_what_another_process_left.py
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


class ReadingWhatAnotherProcessLeftExample:
    """Fills Redis as an earlier process would, damages one entry, and resolves through a fresh lookup.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        redis_client (StandInRedis): The Redis stand-in.
        engine (StandInEngine): The Postgres stand-in.
        redis_tier (MappingRedisTier): The Redis tier over the stand-in.
        postgres_tier (MappingPostgresTier): The Postgres tier over the stand-in.
        statistics (dict): The counters the lookups share.
        lookup (TokenCandidateLookup): The fresh lookup being shown, for Dhan.
    """

    INFY_NSE_ID = '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05'
    TCS_NSE_ID = '8f2b4d6a-0c1e-4a3b-8d5f-7a9c1e3b5d24'

    def __init__(self):
        """Builds the stand-ins, the tiers and a fresh lookup.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 30)
        self.redis_client = StandInRedis()
        self.engine = StandInEngine()
        self.engine.add_answer('b.broker_token = ANY', [
            self.candidate_row('11536', self.TCS_NSE_ID, 'nse', 'nse_equities', 'TCS'),
            self.candidate_row('1594', self.INFY_NSE_ID, 'nse', 'nse_equities', 'INFY'),
        ])
        self.redis_tier = MappingRedisTier(MappingRedisConnection(self.redis_client))
        self.postgres_tier = MappingPostgresTier(self.engine)
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        identity_lookup = InstrumentIdentityLookup(self.redis_tier, self.postgres_tier, self.statistics)
        self.lookup = TokenCandidateLookup(self.redis_tier, self.postgres_tier, self.statistics, 'dhan', identity_lookup)

    def fill_redis_as_another_process(self):
        """Writes both tokens into Redis, then deletes TCS's identity from the identity hash.

        Returns:
            None: This method returns nothing.
        """
        both_tokens = [
            '1594',
            '11536',
        ]
        candidates_by_token = self.postgres_tier.read_token_candidates(self.mapping_date, 'dhan', both_tokens)
        self.redis_tier.write_token_candidates(self.mapping_date, 'dhan', candidates_by_token)
        identity_hash = self.redis_client.values[self.redis_tier.identity_key(self.mapping_date)]
        del identity_hash[self.TCS_NSE_ID]
        self.engine.calls = []
        print(f'Redis holds tokens: {sorted(self.redis_client.values[self.redis_tier.tokens_key(self.mapping_date, "dhan")])}')
        print(f'Redis holds identities for: {sorted(identity_hash)}')

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
        """Resolves three tokens twice through the fresh lookup and prints what each round cost.

        Returns:
            None: This method returns nothing.
        """
        self.fill_redis_as_another_process()
        tokens = [
            '1594',
            '11536',
            '999999',
        ]
        only_complete = self.lookup.read_from_redis(self.mapping_date, tokens)
        print(f'read_from_redis returns only complete tokens: {sorted(only_complete)}')
        answer = self.lookup.resolve(self.mapping_date, tokens)
        for token in tokens:
            symbols = []
            for identity in answer[token]:
                symbols.append(identity['symbol'])
            print(f'Token {token}: {symbols}')
        print(f'  counters: {self.statistics}')
        for fragment, parameters in self.engine.calls:
            print(f'  Postgres was asked for tokens: {parameters["tokens"]}')
        self.lookup.resolve(self.mapping_date, tokens)
        print(f'Second round counters: {self.statistics}')
        print(f'Unknown token remembered: {self.lookup.known("999999")} as {self.lookup.entry("999999")}')
        print(f'A fresh empty_entry is a new list: {self.lookup.empty_entry() is not self.lookup.entry("999999")}')
        refilled = self.lookup.read_from_postgres(self.mapping_date, tokens)
        print(f'read_from_postgres finds tokens: {sorted(refilled)}')
        print(f'write_to_redis: {self.lookup.write_to_redis(self.mapping_date, refilled)}')


if __name__ == '__main__':
    ReadingWhatAnotherProcessLeftExample().run()
