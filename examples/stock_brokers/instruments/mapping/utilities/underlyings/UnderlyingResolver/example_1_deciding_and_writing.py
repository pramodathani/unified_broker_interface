"""Decides which instrument four live derivatives are written on, writes the decisions and counts them.

A derivative names its underlying only by a symbol that does not always match the underlying's own symbol: NSE's NIFTYFPI contracts are written on the index stored as "Nifty FPI 150". Dhan, Groww and Fyers each give the exchange's code for a derivative's underlying, and the resolver looks that code up among the shares, indices and futures on the same exchange in the segments the underlying can be in.

This program takes the three steps `run` would take one at a time: `decisions` reads the derivatives, the codes and the candidates and decides each derivative, `write` replaces the date's stored decisions in one transaction, and `summarise` counts them by segment and status.

The engine is a stand-in that answers from rows held in memory and records what is written, so no PostgreSQL is needed. The codes are made up. Notice that the MCX GOLD option resolves to the GOLD future, because an MCX option is written on a future, that the INFY option resolves to the share even though Dhan and Groww both give the code, and that the RELIANCE future, for which no broker gives a code, is `no_code`.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/underlyings/UnderlyingResolver/example_1_deciding_and_writing.py
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


class DecidingAndWritingExample:
    """Decides, writes and summarises the underlyings of four derivatives on 2026-09-28.

    Attributes:
        database (StandInDatabase): The stand-in rows.
        resolver (UnderlyingResolver): The resolver being shown.
    """

    def __init__(self):
        """Builds the stand-in rows and the resolver over them.

        Returns:
            None: This method returns nothing.
        """
        rows = Rows()
        self.database = StandInDatabase(
            [
                rows.derivative('niftyfpi-future-oct', 'nse', 'nse_equity_index_futures'),
                rows.derivative('infy-option-1600-ce', 'nse', 'nse_equity_options'),
                rows.derivative('gold-option-120000-ce', 'mcx', 'mcx_commodity_options'),
                rows.derivative('reliance-future-oct', 'nse', 'nse_equity_futures'),
            ],
            [
                rows.code('niftyfpi-future-oct', 'fyers', '26074'),
                rows.code('infy-option-1600-ce', 'dhan', '1594'),
                rows.code('infy-option-1600-ce', 'groww', '1594'),
                rows.code('gold-option-120000-ce', 'dhan', '454818'),
            ],
            [
                rows.candidate('nifty-fpi-150-index', 'nse', 'nse_equity_indices', '26074'),
                rows.candidate('infy-share', 'nse', 'nse_equities', '1594'),
                rows.candidate('infy-future-oct', 'nse', 'nse_equity_futures', '53001'),
                rows.candidate('gold-future-dec', 'mcx', 'mcx_commodity_futures', '454818'),
            ],
        )
        self.resolver = UnderlyingResolver(StandInEngine(self.database))

    def run(self):
        """Decides, writes and summarises, printing each step.

        Returns:
            None: This method returns nothing.
        """
        mapping_date = datetime.date(2026, 9, 28)
        decided = self.resolver.decisions(mapping_date)
        for row in decided:
            print(f'{row["instrument_id"]}: {row["status"]}, underlying {row["underlying_instrument_id"]}, codes {row["sources"]}')
        written = self.resolver.write(mapping_date, decided)
        print(f'Rows written: {written}, after deleting {len(self.database.deleted_dates)} earlier set for the date')
        summary = self.resolver.summarise(decided)
        for segment, status in sorted(summary):
            print(f'  {segment} {status}: {summary[(segment, status)]}')


if __name__ == '__main__':
    DecidingAndWritingExample().run()
