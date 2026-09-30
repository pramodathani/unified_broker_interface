"""Runs the contract size command line for one date, the way the daily mapping run does, against a stand-in database.

`ContractSizeCommand.run` reads `--date` from `sys.argv`, builds a `ContractSizeResolver` over the configured PostgreSQL engine, decides and writes the date's contract sizes, and prints how many contracts each segment has in each status.

The command builds its engine through `get_postgres_engine`, so this program replaces that function in the `contract_sizes` module with one returning an in-memory stand-in engine. That keeps the real command and the real resolver running while no database is reached. The stand-in holds three MCX CRUDEOIL futures, two confirmed at 100 barrels by Wisdom Capital and Kotak and one far month listed by Wisdom Capital only, and one BSE USDINR future that only Stoxkart lists.

Notice in the printed table that the far-month CRUDEOIL future is `sibling_confirmed` and that the BSE currency future is tradeable on its single source.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeCommand/example_2_running_for_a_date.py
"""

import sys
import types

from stock_brokers.instruments.mapping.utilities import contract_sizes
from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeCommand,
)


class StandInConnection:
    """A stand-in database connection that answers the resolver's queries from rows in memory.

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
        if 'AS units' in sql:
            return self.database.source_rows.get(parameters['broker'], [])
        return self.database.contract_rows


class StandInDatabase:
    """The rows the stand-in answers with, and the writes it has received.

    Attributes:
        contract_rows (list): The live contracts, as rows with `instrument_id`, `segment` and `underlying_symbol`.
        source_rows (dict): Broker name to the rows of `instrument_id` and `units` its source returns.
        deleted_dates (list): The mapping dates whose decisions were deleted.
        written_rows (list): The decision rows inserted.
    """

    def __init__(self, contract_rows, source_rows):
        """Holds the rows.

        Args:
            contract_rows (list): The live contracts.
            source_rows (dict): Broker name to its source's rows.

        Returns:
            None: This method returns nothing.
        """
        self.contract_rows = contract_rows
        self.source_rows = source_rows
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


class RunningForADateExample:
    """Runs the command for 2026-09-28 over a stand-in database and prints its exit code and what it wrote.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        command (ContractSizeCommand): The command being shown.
    """

    def __init__(self):
        """Builds the stand-in database, points the command's engine at it and sets the arguments.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInDatabase(
            [
                self.contract('crudeoil-2026-10', 'mcx_commodity_futures', 'CRUDEOIL'),
                self.contract('crudeoil-2026-11', 'mcx_commodity_futures', 'CRUDEOIL'),
                self.contract('crudeoil-2027-03', 'mcx_commodity_futures', 'CRUDEOIL'),
                self.contract('bse-usdinr-2026-10', 'bse_currency_futures', 'USDINR'),
            ],
            {
                'wisdom_capital': [
                    self.figure('crudeoil-2026-10', '100'),
                    self.figure('crudeoil-2026-11', '100'),
                    self.figure('crudeoil-2027-03', '100'),
                ],
                'kotak': [
                    self.figure('crudeoil-2026-10', '100'),
                    self.figure('crudeoil-2026-11', '100'),
                ],
                'stoxkart': [
                    self.figure('bse-usdinr-2026-10', '1000'),
                ],
            },
        )
        contract_sizes.get_postgres_engine = self.stand_in_engine
        sys.argv = [
            'contract_sizes',
            '--date',
            '2026-09-28',
        ]
        self.command = ContractSizeCommand()

    def stand_in_engine(self):
        """Builds the stand-in engine the command uses in place of the configured one.

        Returns:
            StandInEngine: An engine over the stand-in database.
        """
        return StandInEngine(self.database)

    def contract(self, instrument_id, segment, underlying_symbol):
        """Builds one live contract row.

        Args:
            instrument_id (str): The contract's instrument id.
            segment (str): Its exchange-prefixed segment.
            underlying_symbol (str): Its underlying's symbol.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            segment=segment,
            underlying_symbol=underlying_symbol,
        )

    def figure(self, instrument_id, units):
        """Builds one source row.

        Args:
            instrument_id (str): The contract's instrument id.
            units (str): The size the source gives.

        Returns:
            types.SimpleNamespace: The row.
        """
        return types.SimpleNamespace(
            instrument_id=instrument_id,
            units=units,
        )

    def run(self):
        """Runs the command and prints its exit code and how many rows it wrote.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.command.run()
        print(f'Exit code: {exit_code}')
        print(f'Rows written: {len(self.database.written_rows)}')


if __name__ == '__main__':
    RunningForADateExample().run()
