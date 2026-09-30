"""Writes a parent order's transitions to the event log and shows how connections are borrowed and returned.

`SyntheticOrderEventLog` is the order engine's record: every transition is written and committed to `unified.synthetic_order_events` before the engine acts on it. It opens connections through a function it is given, keeps a small pool of idle ones, and lends one to each write.

This program passes the log a stand-in database instead of PostgreSQL. The stand-in keeps rows in a list and remembers every statement it ran, so the program can show that `apply_table` runs the real DDL file on a connection of its own that it closes afterwards, that `record` and `record_many` each send one insert, and that the second write reuses the connection the first gave back rather than opening another. It also prints `row`, which turns one event into the values of the table's columns: `detail` becomes JSON, a `uuid.UUID` becomes text and `engine_instance` defaults to the log's own. Every time is given explicitly, so the output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/synthetic_order_event_log/SyntheticOrderEventLog/example_1_writing_events.py
"""

import datetime
import logging
import uuid

from unified_broker_interface.utilities.order_engine.utilities.synthetic_order_event_log import (
    COLUMNS,
    SyntheticOrderEventLog,
)


class MemoryDatabase:
    """A stand-in for PostgreSQL that keeps the event table's rows in a list.

    It understands only the statements `SyntheticOrderEventLog` sends: an insert of whole rows, and a select of rows from a moment onwards, optionally narrowed to some synthetic types.

    Attributes:
        rows (list): Each committed row, as a list of values in column order.
        connections_opened (int): How many connections were opened.
        statements (list): The first words of every statement executed.
        failing_inserts (int): How many of the next inserts raise, to imitate a lost connection.
    """

    def __init__(self):
        """Builds an empty database.

        Returns:
            None: This method returns nothing.
        """
        self.rows = []
        self.connections_opened = 0
        self.statements = []
        self.failing_inserts = 0

    def connect(self):
        """Opens a new connection.

        Returns:
            MemoryConnection: The connection.
        """
        self.connections_opened += 1
        return MemoryConnection(self, self.connections_opened)


class MemoryConnection:
    """A stand-in for a psycopg2 connection to `MemoryDatabase`.

    Attributes:
        database (MemoryDatabase): The database it talks to.
        number (int): Which connection this is, counting from 1.
        pending (list): Rows inserted but not yet committed.
        closed (bool): Whether the connection was closed.
    """

    def __init__(self, database, number):
        """Builds an open connection.

        Args:
            database (MemoryDatabase): The database it talks to.
            number (int): Which connection this is.

        Returns:
            None: This method returns nothing.
        """
        self.database = database
        self.number = number
        self.pending = []
        self.closed = False

    def cursor(self):
        """Opens a cursor on this connection.

        Returns:
            MemoryCursor: The cursor.
        """
        return MemoryCursor(self)

    def commit(self):
        """Makes the pending rows permanent.

        Returns:
            None: This method returns nothing.
        """
        self.database.rows.extend(self.pending)
        self.pending = []

    def rollback(self):
        """Throws the pending rows away.

        Returns:
            None: This method returns nothing.
        """
        self.pending = []

    def close(self):
        """Closes the connection.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True


class MemoryCursor:
    """A stand-in for a psycopg2 cursor, usable in a `with` statement.

    Attributes:
        connection (MemoryConnection): The connection it belongs to.
        fetched (list): The rows the last select found.
    """

    def __init__(self, connection):
        """Builds the cursor.

        Args:
            connection (MemoryConnection): The connection it belongs to.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.fetched = []

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            MemoryCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the `with` block without swallowing an exception.

        Args:
            exception_type (type | None): The exception's class, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (object | None): Its traceback, if one was raised.

        Returns:
            bool: False, so any exception carries on.
        """
        return False

    def execute(self, statement, parameters=None):
        """Runs one statement.

        Args:
            statement (str): The SQL text.
            parameters (list | None): The values for its placeholders.

        Returns:
            None: This method returns nothing.

        Raises:
            ConnectionError: When the database has been told to fail the next insert.
        """
        database = self.connection.database
        first_words = ' '.join(statement.split()[:2])
        database.statements.append(f'connection {self.connection.number}: {first_words}')
        if statement.startswith('insert'):
            if database.failing_inserts > 0:
                database.failing_inserts -= 1
                raise ConnectionError('server closed the connection unexpectedly')
            width = len(COLUMNS)
            for start in range(0, len(parameters), width):
                self.connection.pending.append(parameters[start:start + width])
            return
        if statement.startswith('select'):
            moment = parameters[0]
            types = None
            if len(parameters) > 1:
                types = parameters[1]
            found = []
            for row in database.rows:
                if row[0] < moment:
                    continue
                if types is not None and row[4] not in types:
                    continue
                found.append(row)
            found.sort(key=self.sort_key)
            self.fetched = found

    def sort_key(self, row):
        """The order the select asks for: parent, then sequence, then time.

        Args:
            row (list): One row.

        Returns:
            tuple: The parent id as text, the sequence and the time.
        """
        return (str(row[1]), row[2], row[0])

    def fetchall(self):
        """Returns the rows the last select found.

        Returns:
            list: The rows.
        """
        return self.fetched


class WritingEventsExample:
    """Applies the table, writes a parent's events and prints what reached the stand-in database.

    Attributes:
        database (MemoryDatabase): The stand-in database.
        event_log (SyntheticOrderEventLog): The log being shown.
        parent_order_id (uuid.UUID): The parent the events belong to.
        start (datetime.datetime): When the parent was received.
    """

    def __init__(self):
        """Builds the log over the stand-in database.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
        self.database = MemoryDatabase()
        self.event_log = SyntheticOrderEventLog(self.database.connect, logging.getLogger('event_log'), 'engine-host:4242', maximum_connections=2)
        self.parent_order_id = uuid.UUID('3c9d2e71-0b4f-4a8e-9c61-5f0e2d7a1b88')
        self.start = datetime.datetime(2026, 9, 30, 9, 20, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

    def event(self, sequence, name, milliseconds, **values):
        """Builds one event for the parent.

        Args:
            sequence (int): The event's sequence number.
            name (str): The event's name.
            milliseconds (int): How long after the start it happened.
            **values (object): The other columns to fill.

        Returns:
            dict: The event.
        """
        event = {
            'time': self.start + datetime.timedelta(milliseconds=milliseconds),
            'parent_order_id': self.parent_order_id,
            'sequence': sequence,
            'event': name,
        }
        event.update(values)
        return event

    def run(self):
        """Writes the events and prints what the database received.

        Returns:
            None: This method returns nothing.
        """
        self.event_log.apply_table()
        detail = {
            'body': {
                'quantity': 10,
            },
        }
        received = self.event(1, 'parent_received', 0, synthetic_type='simple', parent_state='received', detail=detail)
        values = self.event_log.row(received)
        print('Row for parent_received:')
        for column, value in zip(COLUMNS, values):
            if value is not None:
                print(f'  {column} = {value!r}')
        self.event_log.record(received)
        self.event_log.record_many([
            self.event(2, 'leg_requested', 20, leg_id=f'{self.parent_order_id}:1', leg_state='sending', broker='zerodha'),
            self.event(3, 'leg_answered', 180, leg_id=f'{self.parent_order_id}:1', leg_state='sent', broker_order_id='250930000123456'),
        ])
        self.event_log.record_many([])
        print(f'Statements run: {self.database.statements}')
        print(f'Connections opened: {self.database.connections_opened}, idle now: {len(self.event_log.idle_connections)}')
        print(f'Rows committed: {len(self.database.rows)}')


if __name__ == '__main__':
    WritingEventsExample().run()
