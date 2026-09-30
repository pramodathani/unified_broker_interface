"""Loads the cost table from the database, starts its daily reload thread, and shows what a failed reload and an empty table do.

A process calls `start` once it is running. That reads `unified.broker_order_costs` through `configurations.get_postgres`, warns about every broker orders can be placed at that the table has no row for, and starts a thread that reloads the table every day at 06:00 IST. A reload that fails keeps the rows already held, and a load that finds the table empty raises `ValueError`, so a process never routes orders without costs.

This program must not touch a real database, so it replaces `configurations.get_postgres` with a small stand-in whose connection answers fixed rows, or refuses to connect when told to. A stand-in logger prints each message on one line instead of writing a traceback. The reload thread would wait until the next 06:00, so the program sets the table's `stop` event and waits for the thread to finish; calling `reload_every_day` once `stop` is set returns at once, which is how the thread ends.

Notice the warning about Groww, which has no row; that the failed reload returns False and leaves both rows in place; and that an empty table is refused.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/broker_cost_table/BrokerCostTable/example_2_loading_and_reloading.py
"""

import psycopg2

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)
from utilities import configurations


class PrintingLogger:
    """A stand-in logger that prints each message on one line."""

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
        """Prints an error message without the traceback a real logger would add.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'ERROR {message}')


class StandInCursor:
    """A stand-in database cursor that answers every query with fixed rows.

    Attributes:
        rows (list): The rows to answer with.
    """

    def __init__(self, rows):
        """Builds the cursor.

        Args:
            rows (list): The rows to answer with.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Opens the cursor.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the cursor.

        Args:
            exception_type (type | None): The exception's type, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (object | None): Its traceback.

        Returns:
            bool: False, so an exception is not swallowed.
        """
        del exception_type
        del exception
        del traceback
        return False

    def execute(self, query):
        """Accepts a query.

        Args:
            query (str): The query.

        Returns:
            None: This method returns nothing.
        """
        del query

    def fetchall(self):
        """Answers the fixed rows.

        Returns:
            list: The rows.
        """
        return list(self.rows)


class StandInConnection:
    """A stand-in database connection whose cursor answers fixed rows.

    Attributes:
        rows (list): The rows every query answers.
    """

    def __init__(self, rows):
        """Builds the connection.

        Args:
            rows (list): The rows every query answers.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def cursor(self):
        """Opens a cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self.rows)

    def close(self):
        """Closes the connection.

        Returns:
            None: This method returns nothing.
        """


class StandInDatabase:
    """Stands in for `configurations.get_postgres`, answering fixed rows or refusing to connect.

    Attributes:
        rows (list): The rows every query answers, in the column order of `unified.broker_order_costs`.
        reachable (bool): Whether connecting succeeds.
    """

    def __init__(self, rows):
        """Builds a reachable stand-in database.

        Args:
            rows (list): The rows every query answers.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.reachable = True

    def connect(self):
        """Hands out a connection, or fails the way an unreachable server does.

        Returns:
            StandInConnection: The connection.

        Raises:
            psycopg2.OperationalError: When the stand-in is unreachable.
        """
        if not self.reachable:
            raise psycopg2.OperationalError('stand-in database is unreachable')
        return StandInConnection(self.rows)


class LoadingAndReloadingExample:
    """Starts a table against a stand-in database, then reloads it after the database goes away.

    Attributes:
        database (StandInDatabase): The stand-in database.
        table (BrokerCostTable): The table being shown.
    """

    def __init__(self):
        """Points `configurations.get_postgres` at the stand-in and builds an empty table.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInDatabase([
            (
                'dhan',
                9,
                480,
                7000,
                None,
                0,
                20,
                20,
            ),
            (
                'zerodha',
                9,
                375,
                None,
                4500,
                0,
                20,
                20,
            ),
        ])
        configurations.get_postgres = self.database.connect
        self.table = BrokerCostTable(PrintingLogger())

    def run(self):
        """Starts, reloads and stops the table, printing what it holds after each step.

        Returns:
            None: This method returns nothing.
        """
        read = self.table.read_rows()
        print(f'read_rows found: {sorted(read)}; the table still holds {len(self.table.rows)} rows')
        broker_names = [
            'dhan',
            'groww',
            'zerodha',
        ]
        self.table.start(broker_names)
        print(f'After start: {sorted(self.table.rows)}, reload thread running: {self.table.reload_thread.is_alive()}')
        print(f'Reload with the database up: {self.table.reload_once()}')
        self.database.reachable = False
        print(f'Reload with the database down: {self.table.reload_once()}')
        print(f'Rows kept: {sorted(self.table.rows)}')
        self.database.reachable = True
        self.database.rows = []
        try:
            self.table.load()
        except ValueError as error:
            print(f'Loading an empty table raised ValueError: {error}')
        self.table.stop.set()
        self.table.reload_thread.join(timeout=1)
        print(f'Reload thread running after stop: {self.table.reload_thread.is_alive()}')
        self.table.reload_every_day()
        print('reload_every_day returned at once, because stop is set')


if __name__ == '__main__':
    LoadingAndReloadingExample().run()
