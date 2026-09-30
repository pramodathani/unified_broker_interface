"""Reads Fyers' order symbol to token dictionary through `CacheCandidateSource.order_symbols`.

Most brokers' ticks carry a token, but a Fyers tick names its instrument by symbol, such as `NSE:SBIN-EQ`. The broker mappings store that symbol as the order symbol, so the resolver asks the candidate source once per mapping date for the whole symbol-to-token dictionary, which is one query against `unified.broker_mappings`. For a day the cache cannot answer, the source returns an empty dictionary without querying at all.

The query goes through the mapping cache's SQLAlchemy engine. This program gives the source a stand-in cache whose `engine` answers that one query with three recorded-looking rows and records the SQL and parameters it was sent, so the output shows exactly what would have been asked of TimescaleDB. When two rows share a symbol, the first token is kept. No database is reached.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/resolution/CacheCandidateSource/example_2_order_symbols_for_fyers.py
"""

import datetime

from stock_brokers.instruments.ticks.utilities.resolution import (
    CacheCandidateSource,
)


class StandInConnection:
    """A stand-in for a SQLAlchemy connection that answers one query with fixed rows.

    Attributes:
        engine (StandInEngine): The engine that opened this connection, which records what was executed.
    """

    def __init__(self, engine):
        """Remembers the engine.

        Args:
            engine (StandInEngine): The engine that opened this connection.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine

    def __enter__(self):
        """Opens the connection.

        Returns:
            StandInConnection: This connection.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Closes the connection.

        Args:
            error_type (type | None): The exception type, if one was raised.
            error (BaseException | None): The exception, if one was raised.
            traceback (object | None): Its traceback.

        Returns:
            bool: False, so an exception is not swallowed.
        """
        return False

    def execute(self, statement, parameters):
        """Records the statement and returns Fyers' rows.

        Args:
            statement (sqlalchemy.TextClause): The SQL.
            parameters (dict): The bound parameters.

        Returns:
            list: Rows of (order_symbol, broker_token).
        """
        self.engine.executed.append((str(statement), parameters))
        return [
            (
                'NSE:SBIN-EQ',
                '3045',
            ),
            (
                'NSE:RELIANCE-EQ',
                '2885',
            ),
            (
                'NSE:SBIN-EQ',
                '99999',
            ),
        ]


class StandInEngine:
    """A stand-in for a SQLAlchemy engine that records every query.

    Attributes:
        executed (list): (SQL, parameters) pairs, in order.
    """

    def __init__(self):
        """Starts with nothing executed.

        Returns:
            None: This method returns nothing.
        """
        self.executed = []

    def connect(self):
        """Opens a stand-in connection.

        Returns:
            StandInConnection: The connection.
        """
        return StandInConnection(self)


class StandInMappingCache:
    """A stand-in for `MappingCache` that knows its mapping date and holds an engine.

    Attributes:
        engine (StandInEngine): The stand-in engine.
        mapping_date (datetime.date): The mapping date the cache holds.
    """

    def __init__(self):
        """Builds the cache for 2026-09-15.

        Returns:
            None: This method returns nothing.
        """
        self.engine = StandInEngine()
        self.mapping_date = datetime.date(2026, 9, 15)

    def resolves_to_current_date(self, as_of_date):
        """Answers the mapping date for a day, or None for a day before it.

        Args:
            as_of_date (datetime.date): The trading day asked about.

        Returns:
            datetime.date | None: The mapping date, or None.
        """
        if as_of_date < self.mapping_date:
            return None
        return self.mapping_date


class OrderSymbolsForFyersExample:
    """Reads Fyers' order symbols for today and for a day the cache cannot answer.

    Attributes:
        cache (StandInMappingCache): The stand-in mapping cache.
        source (CacheCandidateSource): The source being shown.
    """

    def __init__(self):
        """Builds the source over the stand-in cache.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInMappingCache()
        self.source = CacheCandidateSource(self.cache)

    def run(self):
        """Prints the dictionaries and the query that was sent.

        Returns:
            None: This method returns nothing.
        """
        symbols = self.source.order_symbols('fyers', datetime.date(2026, 9, 15))
        print(f'Order symbols on 2026-09-15: {symbols}')
        earlier = self.source.order_symbols('fyers', datetime.date(2026, 9, 1))
        print(f'Order symbols on 2026-09-01: {earlier}')
        print(f'Queries sent: {len(self.cache.engine.executed)}')
        for sql, parameters in self.cache.engine.executed:
            print(f'  {sql}')
            print(f'  {parameters}')


if __name__ == '__main__':
    OrderSymbolsForFyersExample().run()
