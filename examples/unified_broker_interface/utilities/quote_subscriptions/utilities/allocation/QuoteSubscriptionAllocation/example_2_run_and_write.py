"""Runs a whole allocation against stand-in stores and writes each broker's subscription set.

`run` reads the capacities, the mapping date in `unified:mapping:meta`, and the date's mappings, keeps for each live instrument the brokers whose own tick normalizer reads the member back to it, and allocates. `write` then replaces each broker's `<broker>:quotes:subscriptions` set, sets `<broker>:quotes:per_socket`, records the summary in `unified:quotes:allocation`, and answers which brokers changed. The program first calls `read_capacities`, `read_mapping_date` and `read_carriers` on their own to show what each returns. It answers the queries from a stand-in database connection and keeps the keys in a stand-in Redis, so nothing is read from or written to the real stores, and it needs no network and no broker login.

Notice that the option that expired on 2026-09-29 is missing from the carriers and counted as expired rather than allocated, that RELIANCE goes to Zerodha because its preference is lower than Dhan's, and that the second `write` reports no broker changed because the sets are already in place.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/utilities/allocation/QuoteSubscriptionAllocation/example_2_run_and_write.py
"""

import datetime
import json
import logging

from unified_broker_interface.utilities.quote_subscriptions.utilities.allocation import (
    QuoteSubscriptionAllocation,
)

CAPACITY_ROWS = [
    ('dhan', 1, 5000, 3),
    ('zerodha', 1, 4000, 1),
]
MAPPING_ROWS = [
    ('reliance', 'zerodha', '738561', None, 'nse', 'nse_equities', 'security', None),
    ('reliance', 'dhan', '2885', None, 'nse', 'nse_equities', 'security', None),
    ('nifty_option', 'dhan', '35001', None, 'nse', 'nse_equity_index_options', 'option', datetime.date(2026, 11, 24)),
    ('expired_option', 'dhan', '40001', None, 'nse', 'nse_equity_options', 'option', datetime.date(2026, 9, 29)),
]


class StandInCursor:
    """A cursor that answers the capacity query with `CAPACITY_ROWS` and the mapping query with `MAPPING_ROWS`.

    Attributes:
        rows (list): The rows for the last query.
        itersize (int): Set by the allocation; unused.
    """

    def __init__(self):
        """Starts with no rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = []
        self.itersize = None

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
        """Picks the rows that answer a query.

        Args:
            query (str): The query.
            parameters (tuple | None): Unused.

        Returns:
            None: This method returns nothing.
        """
        del parameters
        if 'broker_quote_capacities' in query:
            self.rows = CAPACITY_ROWS
        else:
            self.rows = MAPPING_ROWS

    def fetchall(self):
        """The rows for the last query.

        Returns:
            list: The rows.
        """
        return self.rows

    def __iter__(self):
        """Iterates over the rows for the last query.

        Returns:
            iterator: The rows.
        """
        return iter(self.rows)


class StandInConnection:
    """A database connection that hands out stand-in cursors."""

    def cursor(self, name=None):
        """A new stand-in cursor.

        Args:
            name (str | None): Unused.

        Returns:
            StandInCursor: The cursor.
        """
        del name
        return StandInCursor()


class StandInPipeline:
    """Buffers the commands `write` sends and applies them on `execute`.

    Attributes:
        redis (StandInRedis): Where the commands are applied.
        commands (list): The buffered commands.
    """

    def __init__(self, redis):
        """Starts an empty buffer.

        Args:
            redis (StandInRedis): Where the commands are applied.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.commands = []

    def delete(self, key):
        """Buffers a delete.

        Args:
            key (str): The key.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('delete', key))

    def sadd(self, key, *members):
        """Buffers adding members to a set.

        Args:
            key (str): The set's key.
            *members (str): The members.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('sadd', key, members))

    def rename(self, key, new_key):
        """Buffers a rename.

        Args:
            key (str): The key.
            new_key (str): Its new name.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('rename', key, new_key))

    def set(self, key, value):
        """Buffers setting a string.

        Args:
            key (str): The key.
            value (object): The value.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('set', key, value))

    def execute(self):
        """Applies the buffered commands in order.

        Returns:
            None: This method returns nothing.
        """
        for command in self.commands:
            if command[0] == 'delete':
                self.redis.sets.pop(command[1], None)
                self.redis.strings.pop(command[1], None)
            elif command[0] == 'sadd':
                self.redis.sets.setdefault(command[1], set()).update(command[2])
            elif command[0] == 'rename':
                self.redis.sets[command[2]] = self.redis.sets.pop(command[1])
            else:
                self.redis.set(command[1], command[2])
        self.commands = []


class StandInRedis:
    """Keeps strings and sets in memory, holding the mapping date the allocation reads.

    Attributes:
        strings (dict): String keys to their values.
        sets (dict): Set keys to their members.
    """

    def __init__(self):
        """Starts with only the mapping meta key.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {
            'unified:mapping:meta': json.dumps({'mapping_date': '2026-10-27'}),
        }
        self.sets = {}

    def get(self, key):
        """A string key's value.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.strings.get(key)

    def set(self, key, value):
        """Sets a string key, kept as text as Redis would return it.

        Args:
            key (str): The key.
            value (object): The value.

        Returns:
            None: This method returns nothing.
        """
        self.strings[key] = str(value)

    def smembers(self, key):
        """A set's members.

        Args:
            key (str): The set's key.

        Returns:
            set: A copy of the members.
        """
        return set(self.sets.get(key, set()))

    def pipeline(self, transaction=True):
        """A new buffering pipeline.

        Args:
            transaction (bool): Unused.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)


class RunAndWriteExample:
    """Runs the allocation, writes it twice and prints the keys written.

    Attributes:
        redis (StandInRedis): The stand-in Redis.
        allocation (QuoteSubscriptionAllocation): The allocation being shown.
    """

    def __init__(self):
        """Builds the allocation over the stand-in stores.

        Returns:
            None: This method returns nothing.
        """
        self.redis = StandInRedis()
        logger = logging.getLogger('example')
        logger.setLevel(logging.WARNING)
        self.allocation = QuoteSubscriptionAllocation(StandInConnection(), self.redis, logger)

    def run(self):
        """Reads the pieces, runs, writes, prints the keys, and writes again.

        Returns:
            None: This method returns nothing.
        """
        capacities = self.allocation.read_capacities()
        print(f'Capacities read: {sorted(capacities)}')
        mapping_date = self.allocation.read_mapping_date()
        carriers = self.allocation.read_carriers(mapping_date)
        for instrument_id in sorted(carriers):
            print(f"{instrument_id} can be streamed by: {sorted(carriers[instrument_id]['members'])}")
        summary = self.allocation.run()
        print(f"Mapping date {summary['mapping_date']}: {summary['covered']} of {summary['instruments']} live instruments covered, {summary['expired']} expired")
        print(f'First write changed: {self.allocation.write()}')
        for key in sorted(self.redis.sets):
            print(f'{key}: {sorted(self.redis.sets[key])}')
        for key in sorted(self.redis.strings):
            if key.endswith(':per_socket'):
                print(f'{key}: {self.redis.strings[key]}')
        print(f'Second write changed: {self.allocation.write()}')


if __name__ == '__main__':
    RunAndWriteExample().run()
