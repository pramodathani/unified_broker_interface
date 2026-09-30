"""Decides and writes one mapping date's contract sizes through a stand-in database.

`run` reads the date's live currency and commodity contracts, reads every source's figure for them, decides each contract, writes the decisions to `unified.contract_sizes` in one transaction and returns a count per segment, status and tradeable flag.

The engine here is a stand-in that answers the resolver's queries from a few rows held in memory and records what the resolver writes, so no PostgreSQL is needed. The contracts are made up but realistic: three MCX GOLD futures, of which the newest far month is listed by Groww only; an NCDEX DHANIYA future that only Stoxkart lists; and an MCX ZINC future no source gives a size for.

Notice that the far-month GOLD future becomes `sibling_confirmed`, because the two nearer GOLD futures are confirmed at the same 100 units, and that DHANIYA is tradeable on a single source because NCDEX is one of the single-source markets. Each written row keeps every source's figure, so the reason for the decision can be read back later.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeResolver/example_1_deciding_and_writing_a_date.py
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


class DecidingAndWritingADateExample:
    """Runs the resolver for 2026-09-28 over five contracts and prints the summary and the written rows.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        resolver (ContractSizeResolver): The resolver being shown.
    """

    def __init__(self):
        """Builds the stand-in database and the resolver over it.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInDatabase(
            [
                self.contract('gold-2026-10', 'mcx_commodity_futures', 'GOLD'),
                self.contract('gold-2026-12', 'mcx_commodity_futures', 'GOLD'),
                self.contract('gold-2027-02', 'mcx_commodity_futures', 'GOLD'),
                self.contract('dhaniya-2026-11', 'ncdex_commodity_futures', 'DHANIYA'),
                self.contract('zinc-2026-10', 'mcx_commodity_futures', 'ZINC'),
            ],
            {
                'wisdom_capital': [
                    self.figure('gold-2026-10', '100'),
                    self.figure('gold-2026-12', '100'),
                ],
                'kotak': [
                    self.figure('gold-2026-10', '100.000'),
                ],
                'groww': [
                    self.figure('gold-2026-10', '100'),
                    self.figure('gold-2026-12', '100'),
                    self.figure('gold-2027-02', '100'),
                ],
                'stoxkart': [
                    self.figure('dhaniya-2026-11', '5'),
                ],
            },
        )
        self.resolver = ContractSizeResolver(StandInEngine(self.database))

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
        """Runs the resolver and prints the summary and every written row.

        Returns:
            None: This method returns nothing.
        """
        summary = self.resolver.run(datetime.date(2026, 9, 28))
        print('Summary:')
        for segment, status, tradeable in sorted(summary):
            count = summary[(segment, status, tradeable)]
            print(f'  {segment} {status} tradeable={tradeable}: {count}')
        for deleted_date in self.database.deleted_dates:
            print(f'Decisions deleted first for: {deleted_date.isoformat()}')
        print('Rows written:')
        for row in self.database.written_rows:
            units_text = 'none'
            if row['units_per_lot'] is not None:
                units_text = format(row['units_per_lot'], 'f')
            print(f'  {row["instrument_id"]}: {units_text} {row["status"]} tradeable={row["tradeable"]} sources={row["sources"]}')


if __name__ == '__main__':
    DecidingAndWritingADateExample().run()
