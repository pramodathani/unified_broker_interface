"""Runs the underlyings command line as a dry run for one date, against a stand-in database.

`UnderlyingCommand.run` reads `--date` and `--dry-run` from `sys.argv`, builds an `UnderlyingResolver` over the configured PostgreSQL engine, decides every live derivative's underlying and prints how many derivatives each segment has in each status. With `--dry-run` nothing is written to `unified.underlyings`, which makes it the safe way to look at a date's decisions first.

The command builds its engine through `get_postgres_engine`, so this program replaces that function in the `underlyings` module with one returning an in-memory stand-in engine. That keeps the real command and the real resolver running while no database is reached. The stand-in holds a BSE SENSEX50 future whose code leads to the index stored as "SNSX50", a BANKNIFTY option that resolves to the index, and a TCS future no broker gives a code for; the codes are made up.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/underlyings/UnderlyingCommand/example_2_a_dry_run_for_a_date.py
"""

import sys
import types

from stock_brokers.instruments.mapping.utilities import underlyings
from stock_brokers.instruments.mapping.utilities.underlyings import (
    UnderlyingCommand,
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


class DryRunForADateExample:
    """Runs the command as a dry run for 2026-09-28 and prints its exit code and how much it wrote.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        command (UnderlyingCommand): The command being shown.
    """

    def __init__(self):
        """Builds the stand-in rows, points the command's engine at them and sets the arguments.

        Returns:
            None: This method returns nothing.
        """
        rows = Rows()
        self.database = StandInDatabase(
            [
                rows.derivative('sensex50-future-oct', 'bse', 'bse_equity_index_futures'),
                rows.derivative('banknifty-option-55000-ce', 'nse', 'nse_equity_index_options'),
                rows.derivative('tcs-future-oct', 'nse', 'nse_equity_futures'),
            ],
            [
                rows.code('sensex50-future-oct', 'fyers', '12'),
                rows.code('banknifty-option-55000-ce', 'fyers', '26009'),
            ],
            [
                rows.candidate('snsx50-index', 'bse', 'bse_equity_indices', '12'),
                rows.candidate('nifty-bank-index', 'nse', 'nse_equity_indices', '26009'),
            ],
        )
        underlyings.get_postgres_engine = self.stand_in_engine
        sys.argv = [
            'underlyings',
            '--date',
            '2026-09-28',
            '--dry-run',
        ]
        self.command = UnderlyingCommand()

    def stand_in_engine(self):
        """Builds the stand-in engine the command uses in place of the configured one.

        Returns:
            StandInEngine: An engine over the stand-in rows.
        """
        return StandInEngine(self.database)

    def run(self):
        """Runs the command and prints its exit code and how many rows it wrote.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.command.run()
        print(f'Exit code: {exit_code}')
        print(f'Rows written: {len(self.database.written_rows)}')


if __name__ == '__main__':
    DryRunForADateExample().run()
