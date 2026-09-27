"""The engine's record of every transition, written to `unified.synthetic_order_events` before it is acted on."""

import datetime
import decimal
import json
import pathlib
import threading
import uuid

DDL_FILE = '340_unified_synthetic_order_events.sql'
# The project root: this file is at unified_broker_interface/utilities/order_engine/utilities/, so
# four parents up is unified_broker_interface/ and five is the root the DDL tree hangs off.
DDL_DIRECTORY = (
    pathlib.Path(__file__).resolve().parents[4]
    / 'stock_brokers'
    / 'instruments'
    / 'ticks'
    / 'utilities'
    / 'sql'
    / 'ddl'
)
COLUMNS = [
    'time',
    'parent_order_id',
    'sequence',
    'event',
    'synthetic_type',
    'parent_state',
    'leg_id',
    'leg_role',
    'leg_state',
    'broker',
    'broker_order_id',
    'exchange_order_id',
    'tag_sent',
    'identifier_sent',
    'intent_id',
    'instrument_id',
    'transaction_type',
    'product',
    'order_type',
    'validity',
    'quantity',
    'filled_quantity',
    'price',
    'trigger_price',
    'average_price',
    'outcome',
    'status_message',
    'engine_instance',
    'detail',
]


class SyntheticOrderEventLog:
    """Writes one row per transition, and reads them back to rebuild the engine's state.

    This is the engine's record. Redis holds the same state for speed, but only these rows survive a Redis that was flushed or a machine that was rebooted, so recovery reads from here and treats Redis as a cache.

    A row is written and committed before the action it describes is taken, which is what makes a crash mid-send recoverable. That costs one synchronous database round trip on the order path, measured in the tenths of a millisecond against a broker call of one to three hundred, and is the price of the recovery the rest of this package is built on.

    Attributes:
        connect (callable): Opens a new database connection.
        logger (logging.Logger): The logger.
        engine_instance (str): Which engine wrote the row, for reading a day that spanned a restart.
        maximum_connections (int): The most connections open at once, shared by every worker thread.
        idle_connections (list): The open connections not in use, most recently returned last.
        connections_lock (threading.Lock): Guards `idle_connections`.
        connection_slots (threading.BoundedSemaphore): One slot per connection that may be open, taken while a connection is in use.
    """

    def __init__(self, connect, logger, engine_instance, maximum_connections=8):
        """Builds the log.

        Args:
            connect (callable): Opens a new database connection.
            logger (logging.Logger): The logger.
            engine_instance (str): Which engine is writing, such as the host and pid.
            maximum_connections (int): The most connections open at once; a write beyond that waits for one to come back.

        Returns:
            None: This method returns nothing.
        """
        self.connect = connect
        self.logger = logger
        self.engine_instance = engine_instance
        self.maximum_connections = maximum_connections
        self.idle_connections = []
        self.connections_lock = threading.Lock()
        self.connection_slots = threading.BoundedSemaphore(maximum_connections)

    def apply_table(self):
        """Applies the table's own DDL file, which creates it the first time and changes nothing after.

        Executed through psycopg2 rather than SQLAlchemy's `text()`, which would take the colons in the file's comments for bind parameters.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything the database raises, after rolling back.
        """
        path = DDL_DIRECTORY / DDL_FILE
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(path.read_text())
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        self.logger.info(f'Applied {path.name}.')

    def borrow_connection(self):
        """Takes a connection for one write or read, opening one when none is idle, and waiting while every allowed connection is in use.

        psycopg2 does not allow two threads to use one connection at once, and the engine's worker threads write at the same time, so each write borrows a connection of its own. The pool is small, because each write holds its connection for well under a millisecond, and the database's own connection limit is shared with every other script.

        Returns:
            object: The psycopg2 connection.

        Raises:
            Exception: Anything opening a connection raises, after giving its slot back.
        """
        self.connection_slots.acquire()
        with self.connections_lock:
            if self.idle_connections:
                return self.idle_connections.pop()
        try:
            return self.connect()
        except Exception:
            self.connection_slots.release()
            raise

    def give_back(self, connection):
        """Returns a borrowed connection that is still good.

        Args:
            connection (object): The connection.

        Returns:
            None: This method returns nothing.
        """
        with self.connections_lock:
            self.idle_connections.append(connection)
        self.connection_slots.release()

    def discard(self, connection):
        """Closes a borrowed connection after a failure, so the next write opens a new one.

        Args:
            connection (object): The connection.

        Returns:
            None: This method returns nothing.
        """
        try:
            connection.close()
        except Exception:
            pass
        self.connection_slots.release()

    def record(self, event):
        """Writes one transition and commits it.

        Args:
            event (dict): The row's values by column name; `time`, `parent_order_id`, `sequence` and `event` are required and the rest may be left out.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything the database raises, after closing the connection so the next write opens a new one.
        """
        self.record_many([
            event,
        ])

    def record_many(self, events):
        """Writes several transitions and commits them together.

        Args:
            events (list): One dictionary per row, in the order they happened.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything the database raises, after closing the connection so the next write opens a new one.
        """
        if not events:
            return
        rows = []
        for event in events:
            rows.append(self.row(event))
        placeholders = '(' + ', '.join(['%s'] * len(COLUMNS)) + ')'
        columns = ', '.join(f'"{column}"' for column in COLUMNS)
        statement = (
            f'insert into unified.synthetic_order_events ({columns}) values '
            + ', '.join([placeholders] * len(rows))
        )
        flattened = []
        for row in rows:
            flattened.extend(row)
        connection = self.borrow_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, flattened)
            connection.commit()
        except Exception:
            self.discard(connection)
            raise
        self.give_back(connection)

    def row(self, event):
        """One event as the values of `COLUMNS`, in order.

        A `uuid.UUID` is written as text rather than registering psycopg2's UUID adapter, which is a global change to how every connection in the process behaves and would be an odd thing for an order engine to do to the instrument loader.

        Args:
            event (dict): The row's values by column name.

        Returns:
            list: The values, with `detail` encoded as JSON, identifiers as text and `time` defaulted to now.
        """
        values = []
        for column in COLUMNS:
            value = event.get(column)
            if column == 'time' and value is None:
                value = datetime.datetime.now(datetime.timezone.utc)
            if column == 'engine_instance' and value is None:
                value = self.engine_instance
            if column == 'detail' and value is not None:
                value = json.dumps(value, default=str)
            if isinstance(value, uuid.UUID):
                value = str(value)
            values.append(value)
        return values

    def read_since(self, moment):
        """Every transition recorded at or after `moment`, oldest first within each parent.

        Args:
            moment (datetime.datetime): The start of the window, which is the last 06:00 IST.

        Returns:
            list: One dictionary per row, by column name.

        Raises:
            Exception: Anything the database raises, after closing the connection so the next read opens a new one.
        """
        columns = ', '.join(f'"{column}"' for column in COLUMNS)
        statement = (
            f'select {columns} from unified.synthetic_order_events '
            'where "time" >= %s order by parent_order_id, sequence, "time"'
        )
        connection = self.borrow_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, [
                    moment,
                ])
                fetched = cursor.fetchall()
            connection.commit()
        except Exception:
            self.discard(connection)
            raise
        self.give_back(connection)
        events = []
        for values in fetched:
            event = {}
            for column, value in zip(COLUMNS, values):
                event[column] = self.json_ready(value)
            events.append(event)
        return events

    def read_since_for_types(self, moment, types):
        """Every transition of the named order types recorded at or after `moment`.

        This exists for the handful of types that outlive a trading day. The ordinary recovery scan reads from the last 06:00 IST, which is right for everything that is finished by the close, and would silently forget a stop somebody armed on Monday for a position they mean to hold until Friday.

        It is a separate read rather than a wider window for everything, because the day's events are the overwhelming majority and reading a week of them at every start would grow without bound. This one is narrowed by type, and the types that carry are the ones that place almost nothing.

        Args:
            moment (datetime.datetime): The start of the window.
            types (list): The `synthetic_type` values to read.

        Returns:
            list: One dictionary per row, by column name.

        Raises:
            Exception: Anything the database raises, after closing the connection so the next read opens a new one.
        """
        if not types:
            return []
        columns = ', '.join(f'"{column}"' for column in COLUMNS)
        statement = (
            f'select {columns} from unified.synthetic_order_events '
            'where "time" >= %s and synthetic_type = any(%s) '
            'order by parent_order_id, sequence, "time"'
        )
        connection = self.borrow_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, [
                    moment,
                    list(types),
                ])
                fetched = cursor.fetchall()
            connection.commit()
        except Exception:
            self.discard(connection)
            raise
        self.give_back(connection)
        events = []
        for values in fetched:
            event = {}
            for column, value in zip(COLUMNS, values):
                event[column] = self.json_ready(value)
            events.append(event)
        return events

    def json_ready(self, value):
        """One value from the database as a type the rest of the engine can hold and serialise.

        A `NUMERIC` column comes back as `decimal.Decimal` and a `UUID` column may come back as `uuid.UUID`, and neither survives `json.dumps` when a parent is written to Redis. Converting them here, at the one place rows leave the database, means nothing downstream has to know they were ever anything else. Four decimal places of a price fit a float without loss.

        Args:
            value (object): The value as the database returned it.

        Returns:
            object: The value as a float, a string, or unchanged.
        """
        if isinstance(value, decimal.Decimal):
            return float(value)
        if isinstance(value, uuid.UUID):
            return str(value)
        return value
