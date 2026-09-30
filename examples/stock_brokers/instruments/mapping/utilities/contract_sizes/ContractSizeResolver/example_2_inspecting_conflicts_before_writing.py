"""Decides a date's contract sizes without writing them, to inspect the conflicts first, and then writes them.

`segments` lists every exchange-prefixed currency and commodity futures and options segment the resolver reads. `live_contracts` reads the contracts mapped on the date in those segments, and `decisions` reads every source and decides each contract without writing anything, which is useful to look at the conflicts before `write` replaces the date's stored decisions.

The engine is the same kind of in-memory stand-in as in the first program, so no PostgreSQL is needed. Two troubles are staged here. Stoxkart's file lists one USDINR option twice, with lots of 1000 and 2000, so the contract is a conflict and its recorded figure reads `1000|2000`, even though Kotak and Shoonya agree on 1000. And the MCX SILVERMIC contracts come in two confirmed sizes, as after a lot revision, so the far-month contract that only Groww lists stays `single_source` and untradeable instead of being settled by its siblings.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeResolver/example_2_inspecting_conflicts_before_writing.py
"""

import datetime
import types

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeResolver,
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


class InspectingConflictsBeforeWritingExample:
    """Lists the segments, reads the live contracts, decides them and then writes the decisions.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        engine (StandInEngine): The stand-in engine.
        resolver (ContractSizeResolver): The resolver being shown.
        mapping_date (datetime.date): The date being decided.
    """

    def __init__(self):
        """Builds the stand-in database and the resolver over it.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInDatabase(
            [
                self.contract('usdinr-option-83', 'nse_currency_options', 'USDINR'),
                self.contract('silvermic-2026-11', 'mcx_commodity_futures', 'SILVERMIC'),
                self.contract('silvermic-2027-02', 'mcx_commodity_futures', 'SILVERMIC'),
                self.contract('silvermic-2027-04', 'mcx_commodity_futures', 'SILVERMIC'),
            ],
            {
                'kotak': [
                    self.figure('usdinr-option-83', '1000'),
                    self.figure('silvermic-2026-11', '1'),
                    self.figure('silvermic-2027-02', '5'),
                ],
                'shoonya': [
                    self.figure('usdinr-option-83', '1000'),
                ],
                'stoxkart': [
                    self.figure('usdinr-option-83', '1000'),
                    self.figure('usdinr-option-83', '2000'),
                ],
                'groww': [
                    self.figure('silvermic-2026-11', '1'),
                    self.figure('silvermic-2027-02', '5'),
                    self.figure('silvermic-2027-04', '5'),
                ],
            },
        )
        self.engine = StandInEngine(self.database)
        self.resolver = ContractSizeResolver(self.engine)
        self.mapping_date = datetime.date(2026, 9, 28)

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
        """Prints the segments, the live contracts and the decisions, then writes them.

        Returns:
            None: This method returns nothing.
        """
        segments = self.resolver.segments()
        print(f'{len(segments)} segments are read, starting with {segments[:4]}')
        with self.engine.connect() as connection:
            contracts = self.resolver.live_contracts(connection, self.mapping_date, segments)
        for instrument_id in contracts:
            segment, underlying_symbol = contracts[instrument_id]
            print(f'Live: {instrument_id} in {segment} on {underlying_symbol}')
        rows = self.resolver.decisions(self.mapping_date)
        print(f'Rows written before writing: {len(self.database.written_rows)}')
        for row in rows:
            print(f'  {row["instrument_id"]}: {row["status"]} tradeable={row["tradeable"]} sources={row["sources"]}')
        written = self.resolver.write(self.mapping_date, rows)
        print(f'Rows written: {written}')


if __name__ == '__main__':
    InspectingConflictsBeforeWritingExample().run()
