"""Reads quote capacities from a stand-in `unified.broker_quote_capacities`, the way the allocation does.

`QuoteSubscriptionAllocation.read_capacities` turns every row of the table into a `QuoteCapacity` and keeps only the brokers with room. This program answers that query from a stand-in database connection holding three rows, so nothing is read from PostgreSQL.

It needs no data store, no network and no broker login.

Notice that Groww, with 0 sockets, is not among the capacities read.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/utilities/allocation/QuoteCapacity/example_2_read_from_the_table.py
"""

import logging

from unified_broker_interface.utilities.quote_subscriptions.utilities.allocation import (
    QuoteSubscriptionAllocation,
)


class StandInCursor:
    """A cursor that answers any query with fixed rows.

    Attributes:
        rows (list): The rows to answer with.
    """

    def __init__(self, rows):
        """Holds the rows.

        Args:
            rows (list): The rows to answer with.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Starts a `with` block.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Ends a `with` block.

        Args:
            exception_type (type | None): Unused.
            exception (Exception | None): Unused.
            traceback (object | None): Unused.

        Returns:
            bool: False, so exceptions propagate.
        """
        return False

    def execute(self, query, parameters=None):
        """Accepts a query.

        Args:
            query (str): Unused.
            parameters (tuple | None): Unused.

        Returns:
            None: This method returns nothing.
        """
        del query, parameters

    def fetchall(self):
        """The fixed rows.

        Returns:
            list: The rows.
        """
        return self.rows


class StandInConnection:
    """A database connection whose cursors answer with fixed capacity rows.

    Attributes:
        rows (list): The capacity rows.
    """

    def __init__(self, rows):
        """Holds the rows.

        Args:
            rows (list): The capacity rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def cursor(self, name=None):
        """A cursor over the rows.

        Args:
            name (str | None): Unused.

        Returns:
            StandInCursor: The cursor.
        """
        del name
        return StandInCursor(self.rows)


class ReadFromTheTableExample:
    """Reads three capacity rows and prints the brokers kept.

    Attributes:
        allocation (QuoteSubscriptionAllocation): The allocation reading the table.
    """

    def __init__(self):
        """Builds the allocation over a stand-in connection.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            ('fyers', 1, 100, 2),
            ('groww', 0, 0, 100),
            ('zerodha', 24, 4000, 1),
        ]
        self.allocation = QuoteSubscriptionAllocation(StandInConnection(rows), None, logging.getLogger('example'))

    def run(self):
        """Prints each capacity read.

        Returns:
            None: This method returns nothing.
        """
        capacities = self.allocation.read_capacities()
        for broker, capacity in capacities.items():
            print(f'{broker}: total {capacity.total}, preference {capacity.preference}')


if __name__ == '__main__':
    ReadFromTheTableExample().run()
