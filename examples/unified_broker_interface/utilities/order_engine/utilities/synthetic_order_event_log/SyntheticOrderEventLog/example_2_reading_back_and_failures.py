"""Reads the day's events back for recovery, and shows a failed write closing its connection.

When the engine starts it reads every transition since the last 06:00 IST with `read_since`, and the transitions of the few order types that outlive a day with `read_since_for_types`. Rows come back oldest first within each parent, with `NUMERIC` values turned into floats and UUIDs into text by `json_ready`, so the rebuilt parents can be written to Redis as JSON.

This program passes the log a stand-in database whose rows are written by hand, including a `decimal.Decimal` price and a `uuid.UUID` parent id as psycopg2 would return them. It then makes one insert fail, as a dropped database connection would, and shows that the log closes that connection with `discard`, raises the error, and opens a fresh connection for the next write. It also borrows and returns a connection directly with `borrow_connection` and `give_back`. Every time is fixed, so the output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/synthetic_order_event_log/SyntheticOrderEventLog/example_2_reading_back_and_failures.py
"""

import datetime
import decimal
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


class ReadingBackAndFailuresExample:
    """Reads rows back through the log and makes one write fail.

    Attributes:
        database (MemoryDatabase): The stand-in database.
        event_log (SyntheticOrderEventLog): The log being shown.
        india (datetime.timezone): India's fixed UTC offset.
    """

    def __init__(self):
        """Builds the log over a stand-in database holding four rows.

        Returns:
            None: This method returns nothing.
        """
        self.database = MemoryDatabase()
        self.event_log = SyntheticOrderEventLog(self.database.connect, logging.getLogger('event_log'), 'engine-host:4242')
        self.india = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        self.add_row(datetime.datetime(2026, 9, 29, 14, 0, tzinfo=self.india), 'gtt-1', 1, 'parent_received', 'gtt', None)
        self.add_row(datetime.datetime(2026, 9, 30, 9, 21, tzinfo=self.india), uuid.UUID('9e07aa10-4c2b-4d1e-8f3a-7b6c5d4e3f21'), 2, 'leg_answered', 'simple', decimal.Decimal('812.4000'))
        self.add_row(datetime.datetime(2026, 9, 30, 9, 20, tzinfo=self.india), uuid.UUID('9e07aa10-4c2b-4d1e-8f3a-7b6c5d4e3f21'), 1, 'parent_received', 'simple', None)
        self.add_row(datetime.datetime(2026, 9, 30, 9, 30, tzinfo=self.india), 'gtt-1', 2, 'parameters_changed', 'gtt', None)

    def add_row(self, moment, parent_order_id, sequence, name, synthetic_type, price):
        """Puts one committed row straight into the stand-in database.

        Args:
            moment (datetime.datetime): When the event happened.
            parent_order_id (object): The parent's id, text or a UUID.
            sequence (int): The event's sequence number.
            name (str): The event's name.
            synthetic_type (str): The order type.
            price (decimal.Decimal | None): The price column.

        Returns:
            None: This method returns nothing.
        """
        values = []
        for column in COLUMNS:
            values.append(None)
        values[COLUMNS.index('time')] = moment
        values[COLUMNS.index('parent_order_id')] = parent_order_id
        values[COLUMNS.index('sequence')] = sequence
        values[COLUMNS.index('event')] = name
        values[COLUMNS.index('synthetic_type')] = synthetic_type
        values[COLUMNS.index('price')] = price
        self.database.rows.append(values)

    def show(self, label, events):
        """Prints the events read back.

        Args:
            label (str): What was read.
            events (list): The events.

        Returns:
            None: This method returns nothing.
        """
        print(label)
        for event in events:
            print(f'  {event["time"].isoformat()} {event["parent_order_id"]!r} #{event["sequence"]} {event["event"]} price={event["price"]!r}')

    def run(self):
        """Reads rows back, then makes one write fail.

        Returns:
            None: This method returns nothing.
        """
        since_six = datetime.datetime(2026, 9, 30, 6, 0, tzinfo=self.india)
        self.show('Since 06:00 today:', self.event_log.read_since(since_six))
        since_monday = datetime.datetime(2026, 9, 28, 6, 0, tzinfo=self.india)
        self.show('GTT orders since Monday:', self.event_log.read_since_for_types(since_monday, ['gtt']))
        print(f'No types asked for: {self.event_log.read_since_for_types(since_monday, [])}')
        print(f'json_ready(Decimal("1.2500")) = {self.event_log.json_ready(decimal.Decimal("1.2500"))!r}')
        print(f'json_ready("text") = {self.event_log.json_ready("text")!r}')
        self.database.failing_inserts = 1
        event = {
            'time': datetime.datetime(2026, 9, 30, 9, 31, tzinfo=self.india),
            'parent_order_id': 'gtt-1',
            'sequence': 3,
            'event': 'parent_state_changed',
        }
        try:
            self.event_log.record(event)
        except ConnectionError as error:
            print(f'Write failed: {error}')
        print(f'Idle connections after the failure: {len(self.event_log.idle_connections)}')
        self.event_log.record(event)
        print(f'Retried write committed, connections opened in all: {self.database.connections_opened}')
        connection = self.event_log.borrow_connection()
        print(f'Borrowed connection {connection.number}, idle left: {len(self.event_log.idle_connections)}')
        self.event_log.give_back(connection)
        print(f'Given back, idle now: {len(self.event_log.idle_connections)}')
        broken = self.event_log.borrow_connection()
        self.event_log.discard(broken)
        print(f'Discarded connection {broken.number}: closed={broken.closed}, idle now: {len(self.event_log.idle_connections)}')


if __name__ == '__main__':
    ReadingBackAndFailuresExample().run()
