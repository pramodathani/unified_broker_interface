"""Tries the underlying decision without writing anything, and shows why a code is looked up only in the right segments.

`run` with `dry_run=True` decides every live derivative and returns the count per segment and status, but never touches `unified.underlyings`, which is what `--dry-run` on the command line does. The three reading steps, `live_derivatives`, `underlying_codes` and `candidates`, can also be called on an open connection to look at what the decision is made from.

`decide` then shows the three outcomes other than `resolved`. An NSE commodity future whose code also names an NSE equity index stays `unresolved`, because a commodity future's underlying can only be in the commodities segment and the index is never considered; this is the reason the lookup is restricted by segment. An option whose code leads to two different instruments is `ambiguous`. A derivative no broker gives a code for is `no_code`.

The engine is a stand-in answering from rows in memory, so no PostgreSQL is needed; the codes are made up.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/underlyings/UnderlyingResolver/example_2_a_dry_run.py
"""

import datetime
import types

from stock_brokers.instruments.mapping.utilities.underlyings import (
    UnderlyingResolver,
)


class StandInConnection:
    """A stand-in database connection that answers the resolver's three queries from rows in memory and records writes.

    Attributes:
        database (StandInDatabase): The rows and the record of writes.
    """

    def __init__(self, database):
        """Holds the stand-in database.

        Args:
            database (StandInDatabase): The rows and the record of writes.

        Returns:
            None: This method returns nothing.
        """
        self.database = database

    def __enter__(self):
        """Opens the connection.

        Returns:
            StandInConnection: This connection.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Closes the connection.

        Args:
            error_type (type | None): The exception type raised inside the block, if any.
            error (BaseException | None): The exception raised inside the block, if any.
            traceback (types.TracebackType | None): The traceback, if any.

        Returns:
            bool: False, so an exception is never swallowed.
        """
        return False

    def execute(self, statement, parameters):
        """Answers one query from the rows in memory, or records one write.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement.
            parameters (dict | list): The statement's parameters, or a list of them for a batch insert.

        Returns:
            list: The rows the query returns, empty for a write.
        """
        sql = str(statement)
        if sql.startswith('DELETE'):
            self.database.deleted_dates.append(parameters['mapping_date'])
            return []
        if sql.startswith('INSERT'):
            for row in parameters:
                self.database.written_rows.append(row)
            return []
        if sql.startswith('SELECT m.instrument_id, m.broker'):
            return self.database.code_rows
        if 'CASE WHEN' in sql:
            return self.database.candidate_rows
        return self.database.derivative_rows


class StandInDatabase:
    """The rows the stand-in answers with, and the writes it has received.

    Attributes:
        derivative_rows (list): The live derivatives, as rows with `instrument_id`, `exchange` and `segment`.
        code_rows (list): The codes brokers give, as rows with `instrument_id`, `broker` and `code`.
        candidate_rows (list): The candidates, as rows with `instrument_id`, `exchange`, `segment` and `code`.
        deleted_dates (list): The mapping dates whose decisions were deleted.
        written_rows (list): The decision rows inserted.
    """

    def __init__(self, derivative_rows, code_rows, candidate_rows):
        """Holds the rows.

        Args:
            derivative_rows (list): The live derivatives.
            code_rows (list): The codes brokers give.
            candidate_rows (list): The candidates.

        Returns:
            None: This method returns nothing.
        """
        self.derivative_rows = derivative_rows
        self.code_rows = code_rows
        self.candidate_rows = candidate_rows
        self.deleted_dates = []
        self.written_rows = []


class StandInEngine:
    """A stand-in SQLAlchemy engine whose connections all share one stand-in database.

    Attributes:
        database (StandInDatabase): The shared rows.
    """

    def __init__(self, database):
        """Holds the database.

        Args:
            database (StandInDatabase): The shared rows.

        Returns:
            None: This method returns nothing.
        """
        self.database = database

    def connect(self):
        """Opens a connection for reading.

        Returns:
            StandInConnection: A connection over the shared rows.
        """
        return StandInConnection(self.database)

    def begin(self):
        """Opens a connection inside a transaction.

        Returns:
            StandInConnection: A connection over the shared rows.
        """
        return StandInConnection(self.database)


class Rows:
    """Builds the three kinds of stand-in row."""

    def derivative(self, instrument_id, exchange, segment):
        """Builds one live derivative row.

        Args:
            instrument_id (str): The derivative's instrument id.
            exchange (str): Its exchange.
            segment (str): Its exchange-prefixed segment.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            exchange=exchange,
            segment=segment,
        )

    def code(self, instrument_id, broker, code):
        """Builds one row of the code a broker gives for a derivative's underlying.

        Args:
            instrument_id (str): The derivative's instrument id.
            broker (str): The broker.
            code (str): The exchange code it gives.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            broker=broker,
            code=code,
        )

    def candidate(self, instrument_id, exchange, segment, code):
        """Builds one candidate row.

        Args:
            instrument_id (str): The candidate's instrument id.
            exchange (str): Its exchange.
            segment (str): Its exchange-prefixed segment.
            code (str): Its exchange code.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            exchange=exchange,
            segment=segment,
            code=code,
        )


class DryRunExample:
    """Runs a dry run over three derivatives, reads the inputs and decides three edge cases.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        engine (StandInEngine): The stand-in engine.
        resolver (UnderlyingResolver): The resolver being shown.
        mapping_date (datetime.date): The date being decided.
    """

    def __init__(self):
        """Builds the stand-in rows and the resolver over them.

        Returns:
            None: This method returns nothing.
        """
        rows = Rows()
        self.database = StandInDatabase(
            [
                rows.derivative('crude-future-nse-oct', 'nse', 'nse_commodity_futures'),
                rows.derivative('sbin-option-800-pe', 'nse', 'nse_equity_options'),
                rows.derivative('usdinr-future-oct', 'nse', 'nse_currency_futures'),
            ],
            [
                rows.code('crude-future-nse-oct', 'dhan', '26000'),
                rows.code('sbin-option-800-pe', 'dhan', '3045'),
                rows.code('sbin-option-800-pe', 'groww', '3045'),
            ],
            [
                rows.candidate('nifty-50-index', 'nse', 'nse_equity_indices', '26000'),
                rows.candidate('sbin-share', 'nse', 'nse_equities', '3045'),
                rows.candidate('sbin-future-oct', 'nse', 'nse_equity_futures', '3045'),
            ],
        )
        self.engine = StandInEngine(self.database)
        self.resolver = UnderlyingResolver(self.engine)
        self.mapping_date = datetime.date(2026, 9, 28)

    def run(self):
        """Prints the dry run's counts, the inputs and three direct decisions.

        Returns:
            None: This method returns nothing.
        """
        summary = self.resolver.run(self.mapping_date, dry_run=True)
        for segment, status in sorted(summary):
            print(f'{segment} {status}: {summary[(segment, status)]}')
        print(f'Rows written by the dry run: {len(self.database.written_rows)}')
        with self.engine.connect() as connection:
            derivatives = self.resolver.live_derivatives(connection, self.mapping_date)
            codes = self.resolver.underlying_codes(connection, self.mapping_date)
            candidates = self.resolver.candidates(connection, self.mapping_date)
        print(f'Derivatives: {derivatives}')
        print(f'Codes: {dict(codes)}')
        for key in sorted(candidates):
            print(f'Candidate {key}: {sorted(candidates[key])}')
        underlying, status = self.resolver.decide(
            'nse',
            'nse_commodity_futures',
            {
                'dhan': '26000',
            },
            candidates,
        )
        print(f'NSE commodity future with code 26000: {status}, {underlying}')
        underlying, status = self.resolver.decide(
            'nse',
            'nse_equity_options',
            {
                'dhan': '3045',
            },
            candidates,
        )
        print(f'NSE equity option with code 3045: {status}, {underlying}')
        underlying, status = self.resolver.decide(
            'nse',
            'nse_currency_futures',
            {},
            candidates,
        )
        print(f'NSE currency future with no code: {status}, {underlying}')


if __name__ == '__main__':
    DryRunExample().run()
