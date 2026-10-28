"""Loads the charge rate table from the database, starts its daily reload thread, and shows what a failed reload and an empty table do.

A process calls `start` once it is running. That reads `unified.charge_rates` through `configurations.get_postgres` and starts a thread that reloads the table every day at 06:00 IST. A reload that fails keeps the rows already held. An empty charge rate table is not an error: every lookup then answers None, so no trade's charges are known, and `start` logs a warning saying so.

This program must not touch a real database, so it replaces `configurations.get_postgres` with a small stand-in whose connection answers fixed rows, or refuses to connect when told to. A stand-in logger prints each message on one line. The reload thread would wait until the next 06:00, so the program sets the table's `stop` event and waits for the thread to finish.

Notice that the failed reload returns False and keeps both rows, and that starting a second table against an empty database warns instead of raising.

Run it from the project root:

    python examples/unified_broker_interface.utilities.execution_costs.charge_rate_table/ChargeRateTable/example_3_loading_and_reloading.py
"""

import datetime
import decimal

import psycopg2

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRateTable,
)
from utilities import configurations


class PrintingLogger:
    """A logger that prints each message on one line."""

    def info(self, message):
        """Prints an information message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'INFO {message}')

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'WARNING {message}')

    def exception(self, message):
        """Prints an error without the traceback.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'ERROR {message}')


class StandInCursor:
    """A cursor that answers every query with fixed rows.

    Attributes:
        rows (list): The rows to answer with.
    """

    def __init__(self, rows):
        """Builds the cursor.

        Args:
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            exception_type (type | None): The exception's type.
            exception (BaseException | None): The exception.
            traceback (types.TracebackType | None): The traceback.

        Returns:
            bool: False.
        """
        del exception_type
        del exception
        del traceback
        return False

    def execute(self, query):
        """Accepts the query.

        Args:
            query (str): The SQL.

        Returns:
            None: This method returns nothing.
        """
        del query

    def fetchall(self):
        """The fixed rows.

        Returns:
            list: The rows.
        """
        return self.rows


class StandInConnection:
    """A connection whose cursor answers fixed rows.

    Attributes:
        rows (list): The rows.
    """

    def __init__(self, rows):
        """Builds the connection.

        Args:
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def cursor(self):
        """A cursor over the rows.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self.rows)

    def close(self):
        """Closes nothing.

        Returns:
            None: This method returns nothing.
        """


class StandInDatabase:
    """Stands in for `configurations.get_postgres`, answering fixed rows or refusing to connect.

    Attributes:
        rows (list): The rows every query answers.
        reachable (bool): Whether a connection can be made.
    """

    def __init__(self, rows):
        """Builds the database.

        Args:
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.reachable = True

    def connect(self):
        """Opens a stand-in connection, or fails as PostgreSQL would when it cannot be reached.

        Returns:
            StandInConnection: The connection.

        Raises:
            psycopg2.OperationalError: When the database is not reachable.
        """
        if not self.reachable:
            raise psycopg2.OperationalError('could not connect to server')
        return StandInConnection(self.rows)


class LoadingAndReloadingExample:
    """Starts, reloads and stops a charge rate table against a stand-in database.

    Attributes:
        database (StandInDatabase): The stand-in database.
        table (ChargeRateTable): The table.
    """

    def __init__(self):
        """Points `configurations.get_postgres` at the stand-in and builds an empty table.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInDatabase([
            ('nse_equity_index_options', 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'), datetime.date(2026, 10, 19)),
            ('nse_equities', 'delivery', decimal.Decimal('0.001'), decimal.Decimal('0.001'), decimal.Decimal('0.0000307'), decimal.Decimal('0.000001'), decimal.Decimal('0.00015'), decimal.Decimal('0.18'), None),
        ])
        configurations.get_postgres = self.database.connect
        self.table = ChargeRateTable(PrintingLogger())

    def run(self):
        """Reads, starts, reloads and stops the table, printing what it holds after each step.

        Returns:
            None: This method returns nothing.
        """
        read = self.table.read_rows()
        print(f'read_rows found: {sorted(read)}; the table still holds {len(self.table.rows)} rows')
        self.table.start()
        print(f'After start: {sorted(self.table.rows)}, reload thread running: {self.table.reload_thread.is_alive()}')
        print(f'Reload with the database up: {self.table.reload_once()}')
        self.database.reachable = False
        print(f'Reload with the database down: {self.table.reload_once()}')
        print(f'Rows kept: {len(self.table.rows)}')
        self.database.reachable = True
        self.table.stop.set()
        self.table.reload_thread.join(timeout=1)
        print(f'Reload thread running after stop: {self.table.reload_thread.is_alive()}')
        self.table.reload_every_day()
        print('reload_every_day returned at once, because stop is set')
        self.database.rows = []
        empty_table = ChargeRateTable(PrintingLogger())
        empty_table.load()
        print(f'An empty table loads without error; loaded: {empty_table.is_loaded()}')
        empty_table.stop.set()
        empty_table.start()
        empty_table.reload_thread.join(timeout=1)
        five_in_the_morning = datetime.datetime(2026, 10, 19, 5, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        print(f'Seconds from 05:00 IST to the next reload: {empty_table.seconds_until_reload(five_in_the_morning):.0f}')


if __name__ == '__main__':
    LoadingAndReloadingExample().run()
