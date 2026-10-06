"""A stand-in database for measuring execution costs offline, holding scripted engine events, instruments and ticks.

`ExecutionCostMeasurement` sends four kinds of statement: the event query, the segment query, the quote query and, when writing, the table's DDL, a delete and an insert. The stand-in answers the first three from what a program scripted, choosing the quote the way the real query does, and records the rest, so `python -m test_runs.execution_costs` and the example programs run without PostgreSQL.

Typical usage:

    database = StandInExecutionDatabase()
    database.add_tick(INSTRUMENT, moment, '238.00', '238.50')
    measurement = ExecutionCostMeasurement(database.connect, logger)
"""

import decimal

from unified_broker_interface.utilities.execution_costs.execution_cost_measurement import (
    EVENT_COLUMNS,
)


class StandInExecutionDatabase:
    """Scripted rows of `unified.synthetic_order_events`, `unified.instruments` and `unified.ticks`, and a record of what was written.

    Attributes:
        events (list): The scripted event rows, as tuples in `EVENT_COLUMNS` order.
        sequences (dict): The last sequence number given out for each parent.
        segments (dict): Each instrument id (str) to its segment (str).
        ticks (dict): Each instrument id (str) to a list of tuples (time, bid, ask).
        statements (list): Every statement executed, as its first word, such as `SELECT` or `DELETE`, or `DDL` for the table's file.
        inserted (list): Every row inserted, as a list of values in column order.
        deleted_between (list): The (start, end) of every delete.
        transactions (list): `COMMIT` and `ROLLBACK`, in the order they happened.
        fail_on_insert (bool): Whether an insert raises, to show a write rolling back.
    """

    def __init__(self):
        """Builds an empty database.

        Returns:
            None: This method returns nothing.
        """
        self.events = []
        self.sequences = {}
        self.segments = {}
        self.ticks = {}
        self.statements = []
        self.inserted = []
        self.deleted_between = []
        self.transactions = []
        self.fail_on_insert = False

    def add_event(self, time, parent_order_id, event, **columns):
        """Adds one event row, numbering it after the parent's last one.

        Args:
            time (datetime.datetime): When the engine recorded it.
            parent_order_id (str): The parent.
            event (str): The event's name, such as `leg_requested`.
            **columns: Any other column of `EVENT_COLUMNS`, such as `leg_id` or `average_price`; prices may be given as strings.

        Returns:
            None: This method returns nothing.
        """
        sequence = self.sequences.get(parent_order_id, 0) + 1
        self.sequences[parent_order_id] = sequence
        values = {
            'time': time,
            'parent_order_id': parent_order_id,
            'sequence': sequence,
            'event': event,
        }
        for name, value in columns.items():
            if name == 'average_price' and value is not None:
                value = decimal.Decimal(value)
            values[name] = value
        row = []
        for column in EVENT_COLUMNS:
            row.append(values.get(column))
        self.events.append(tuple(row))

    def add_tick(self, instrument_id, time, bid, ask):
        """Adds one stored quote.

        Args:
            instrument_id (str): The instrument.
            time (datetime.datetime): When the tick was received.
            bid (str | None): The best bid, or None for an empty side.
            ask (str | None): The best ask, or None for an empty side.

        Returns:
            None: This method returns nothing.
        """
        bid_price = None
        if bid is not None:
            bid_price = decimal.Decimal(bid)
        ask_price = None
        if ask is not None:
            ask_price = decimal.Decimal(ask)
        self.ticks.setdefault(instrument_id, []).append((time, bid_price, ask_price))

    def connect(self):
        """Opens a stand-in connection, as `get_postgres` would open a real one.

        Returns:
            StandInConnection: The connection.
        """
        return StandInConnection(self)

    def quote_at(self, instrument_id, moment, oldest):
        """The latest tick with both sides of the book after one moment and at or before another, as the real quote query chooses it.

        Args:
            instrument_id (str): The instrument.
            moment (datetime.datetime): The latest time allowed.
            oldest (datetime.datetime): The time the tick must be after.

        Returns:
            tuple | None: (time, bid, ask), or None.
        """
        chosen = None
        for tick in self.ticks.get(instrument_id, []):
            time, bid, ask = tick
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                continue
            if time <= oldest or time > moment:
                continue
            if chosen is None or time > chosen[0]:
                chosen = tick
        return chosen


class StandInConnection:
    """A connection to the stand-in database.

    Attributes:
        database (StandInExecutionDatabase): The database.
    """

    def __init__(self, database):
        """Builds the connection.

        Args:
            database (StandInExecutionDatabase): The database.

        Returns:
            None: This method returns nothing.
        """
        self.database = database

    def cursor(self):
        """Opens a cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self.database)

    def commit(self):
        """Records a commit.

        Returns:
            None: This method returns nothing.
        """
        self.database.transactions.append('COMMIT')

    def rollback(self):
        """Records a rollback.

        Returns:
            None: This method returns nothing.
        """
        self.database.transactions.append('ROLLBACK')

    def close(self):
        """Closes nothing, since nothing was opened.

        Returns:
            None: This method returns nothing.
        """


class StandInCursor:
    """A cursor that answers the measurement's queries from the stand-in database.

    Attributes:
        database (StandInExecutionDatabase): The database.
        answer (list): The rows the last query returned.
    """

    def __init__(self, database):
        """Builds the cursor.

        Args:
            database (StandInExecutionDatabase): The database.

        Returns:
            None: This method returns nothing.
        """
        self.database = database
        self.answer = []

    def __enter__(self):
        """Opens the cursor in a `with` statement.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Closes the cursor at the end of a `with` statement.

        Args:
            error_type (type | None): The exception's class, if one was raised.
            error (BaseException | None): The exception, if one was raised.
            traceback (types.TracebackType | None): Its traceback.

        Returns:
            bool: False, so an exception carries on.
        """
        return False

    def execute(self, statement, parameters=None):
        """Answers a query or records a statement.

        Args:
            statement (str): The SQL.
            parameters (tuple | None): Its parameters.

        Returns:
            None: This method returns nothing.
        """
        text = statement.strip()
        if text.startswith('CREATE SCHEMA'):
            self.database.statements.append('DDL')
            return
        self.database.statements.append(text.split()[0])
        if 'unified.synthetic_order_events' in text:
            self.answer = list(self.database.events)
        elif 'unified.instruments' in text:
            self.answer = []
            for instrument_id in parameters[0]:
                if instrument_id in self.database.segments:
                    self.answer.append((instrument_id, self.database.segments[instrument_id]))
        elif 'unified.ticks' in text:
            instrument_id, moment, oldest = parameters
            self.answer = []
            chosen = self.database.quote_at(instrument_id, moment, oldest)
            if chosen is not None:
                self.answer.append(chosen)
        elif text.startswith('DELETE'):
            self.database.deleted_between.append(parameters)

    def executemany(self, statement, rows):
        """Records the rows of an insert.

        Args:
            statement (str): The SQL.
            rows (list): The rows, each a list of values.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the database was told to fail inserts.
        """
        self.database.statements.append(statement.split()[0])
        if self.database.fail_on_insert:
            raise RuntimeError('the stand-in database refuses inserts')
        for row in rows:
            self.database.inserted.append(list(row))

    def fetchall(self):
        """The rows the last query returned.

        Returns:
            list: The rows, as tuples.
        """
        return self.answer

    def fetchone(self):
        """The first row the last query returned.

        Returns:
            tuple | None: The row, or None.
        """
        if not self.answer:
            return None
        return self.answer[0]
