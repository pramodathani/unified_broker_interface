"""Shows that an unknown instrument id is asked about again every time, and that a Redis outage only costs a query.

An `InstrumentIdentityLookup` does not remember a miss. An instrument id that `unified.instruments` does not carry is a caller's mistake rather than a fact about today's mapping, and the id may appear with tomorrow's master, so its `empty_entry` stays the base class's None and every look-up of it goes to Postgres.

This program builds the lookup with a Redis tier whose client cannot be reached, because `redis_configuration` is pointed at port 9 on this machine where nothing listens, and a stand-in Postgres engine that holds one real instrument and records the parameters of every query. It asks for that instrument and a mistyped id twice.

Notice three things. The known instrument is answered by Postgres the first time and by process memory the second, even with Redis down, because the process tier needs no Redis. The mistyped id is absent from both answers, counted as a miss both times, and appears in both queries' parameters. And the lookup never raised: an unreachable Redis reads as empty and a failed write answers False.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/InstrumentIdentityLookup/example_2_unknown_ids_are_not_remembered.py
"""

import datetime
import types
import uuid

from stock_brokers.instruments.mapping.utilities.cache import (
    InstrumentIdentityLookup,
    MappingPostgresTier,
    MappingRedisTier,
)
from utilities.configurations import redis_configuration


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


class UnknownIdsExample:
    """Asks for a known and an unknown instrument id twice, with Redis unreachable.

    Attributes:
        mapping_date (datetime.date): The mapping date asked about.
        engine (StandInEngine): The Postgres stand-in.
        statistics (dict): The counters the lookup counts into.
        lookup (InstrumentIdentityLookup): The lookup being shown.
    """

    RELIANCE_ID = '9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4'
    MISTYPED_ID = '9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b5'

    def __init__(self):
        """Points Redis at a closed port and builds the tiers and the lookup.

        Returns:
            None: This method returns nothing.
        """
        redis_configuration['host'] = '127.0.0.1'
        redis_configuration['port'] = 9
        self.mapping_date = datetime.date(2026, 9, 30)
        self.engine = StandInEngine()
        self.engine.add_answer('SELECT instrument_id, exchange', [
            types.SimpleNamespace(
                instrument_id=uuid.UUID(self.RELIANCE_ID),
                exchange='bse',
                segment='bse_equities',
                shape='security',
                symbol='RELIANCE',
                underlying_symbol=None,
                expiry_date=None,
                strike_price=None,
                option_type=None,
            ),
        ])
        self.statistics = {
            'process_hits': 0,
            'redis_hits': 0,
            'postgres_hits': 0,
            'misses': 0,
        }
        self.lookup = InstrumentIdentityLookup(MappingRedisTier(), MappingPostgresTier(self.engine), self.statistics)

    def run(self):
        """Resolves both ids twice and prints the answers, counters and queries.

        Returns:
            None: This method returns nothing.
        """
        keys = [
            self.RELIANCE_ID,
            self.MISTYPED_ID,
        ]
        for attempt in range(1, 3):
            answer = self.lookup.resolve(self.mapping_date, keys)
            symbols = []
            for identity in answer.values():
                symbols.append(f'{identity["exchange"]}:{identity["symbol"]}')
            print(f'Attempt {attempt} answered: {symbols}')
            print(f'  counters: {self.statistics}')
        print(f'Mistyped id remembered: {self.lookup.known(self.MISTYPED_ID)}')
        print(f'empty_entry: {self.lookup.empty_entry()}')
        for fragment, parameters in self.engine.calls:
            print(f'Postgres was asked for: {parameters["instrument_identifiers"]}')
        print(f'read_from_redis with Redis down: {self.lookup.read_from_redis(self.mapping_date, keys)}')
        entries = self.lookup.read_from_postgres(self.mapping_date, keys)
        print(f'write_to_redis with Redis down: {self.lookup.write_to_redis(self.mapping_date, entries)}')


if __name__ == '__main__':
    UnknownIdsExample().run()
