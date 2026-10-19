"""A stand-in database for measuring stop slippage offline, holding scripted engine events, instrument segments and measured slips.

`StopSlippageMeasurement` sends the event query, the segment query and, when writing, the table's DDL, a delete and an insert. `StopSlipAllowance` reads the measured slips. The stand-in answers the reads from what a program scripted and records the writes, so `python -m test_runs.stop_slippage` and the example programs run without PostgreSQL.

Typical usage:

    database = StandInStopDatabase()
    database.add_stop(moment, 'stop-1', OPTION, '196.15', fill_price='194.60')
    measurement = StopSlippageMeasurement(database.connect, logger)
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.stop_slippage_measurement import (
    EVENT_COLUMNS,
)


class StandInStopDatabase:
    """Scripted event rows, segments and slips, and the statements written against them.

    Attributes:
        events (list): Event rows as dicts by column name, in the order added.
        segments (dict): Each instrument id (str) to its segment (str).
        slips (list): Tuples of segment, side and slip in basis points, as `unified.stop_slippage` would answer them.
        written (list): The rows the insert was given, as lists of values.
        deleted (list): The parameters each delete was given.
        statements (list): The first word of every statement executed, in order.
        sequence (int): The last sequence number handed out.
    """

    def __init__(self):
        """Builds an empty database.

        Returns:
            None: This method returns nothing.
        """
        self.events = []
        self.segments = {}
        self.slips = []
        self.written = []
        self.deleted = []
        self.statements = []
        self.sequence = 0

    def add_event(self, time, parent_order_id, event, **columns):
        """Adds one event row.

        Args:
            time (datetime.datetime): When it happened.
            parent_order_id (str): The parent it belongs to.
            event (str): The event's name.
            **columns: Any other column of `EVENT_COLUMNS`, such as `leg_id` or `detail`.

        Returns:
            None: This method returns nothing.
        """
        self.sequence = self.sequence + 1
        row = {}
        for column in EVENT_COLUMNS:
            row[column] = None
        row['time'] = time
        row['parent_order_id'] = parent_order_id
        row['sequence'] = self.sequence
        row['event'] = event
        for name, value in columns.items():
            row[name] = value
        self.events.append(row)

    def add_stop(self, fired_at, parent_order_id, instrument_id, trigger, direction='at_or_below', fill_price=None):
        """Adds a protective stop received a minute before it fired, its firing, its order and, when given, its fill.

        Args:
            fired_at (datetime.datetime): When its trigger fired.
            parent_order_id (str): Its parent order id.
            instrument_id (str): The instrument it protects.
            trigger (str): The trigger level.
            direction (str): `at_or_below` for a sell stop, `at_or_above` for a buy stop.
            fill_price (str | None): The price its own order filled at, or None when it did not fill.

        Returns:
            None: This method returns nothing.
        """
        order = {
            'side': 'protect',
            'trigger': {
                'price_crosses': {
                    'field': 'bid' if direction == 'at_or_below' else 'ask',
                    'level': float(trigger),
                    'direction': direction,
                },
            },
        }
        received_at = fired_at - datetime.timedelta(minutes=1)
        self.add_event(received_at, parent_order_id, 'parent_received', synthetic_type='plan', instrument_id=instrument_id, detail={'parameters': {'plan': {'order': order}}})
        fired_detail = {'parameters': {'parts': {'root': {'fired_at': fired_at.timestamp()}}}}
        self.add_event(fired_at, parent_order_id, 'parameters_changed', synthetic_type='plan', detail=fired_detail)
        side = 'SELL' if direction == 'at_or_below' else 'BUY'
        self.add_event(fired_at, parent_order_id, 'leg_requested', synthetic_type='plan', leg_id=f'{parent_order_id}:1', instrument_id=instrument_id, transaction_type=side)
        if fill_price is not None:
            filled_at = fired_at + datetime.timedelta(seconds=2)
            self.add_event(filled_at, parent_order_id, 'leg_update', synthetic_type='plan', leg_id=f'{parent_order_id}:1', filled_quantity=65, average_price=decimal.Decimal(fill_price))

    def add_order(self, requested_at, parent_order_id, instrument_id, transaction_type, fill_price=None):
        """Adds a plain order requested at a moment and, when given, its fill two seconds later.

        Args:
            requested_at (datetime.datetime): When its leg was requested.
            parent_order_id (str): Its parent order id.
            instrument_id (str): The instrument.
            transaction_type (str): `BUY` or `SELL`.
            fill_price (str | None): Its fill price, or None when it did not fill.

        Returns:
            None: This method returns nothing.
        """
        self.add_event(requested_at, parent_order_id, 'parent_received', synthetic_type='simple', instrument_id=instrument_id, detail={'body': {}})
        self.add_event(requested_at, parent_order_id, 'leg_requested', synthetic_type='simple', leg_id=f'{parent_order_id}:1', instrument_id=instrument_id, transaction_type=transaction_type)
        if fill_price is not None:
            filled_at = requested_at + datetime.timedelta(seconds=2)
            self.add_event(filled_at, parent_order_id, 'leg_update', synthetic_type='simple', leg_id=f'{parent_order_id}:1', filled_quantity=65, average_price=decimal.Decimal(fill_price))

    def connect(self):
        """Opens a stand-in connection.

        Returns:
            StandInStopConnection: The connection.
        """
        return StandInStopConnection(self)


class StandInStopConnection:
    """A connection to the stand-in database.

    Attributes:
        database (StandInStopDatabase): The database.
    """

    def __init__(self, database):
        """Builds the connection.

        Args:
            database (StandInStopDatabase): The database.

        Returns:
            None: This method returns nothing.
        """
        self.database = database

    def cursor(self):
        """A cursor on the database.

        Returns:
            StandInStopCursor: The cursor.
        """
        return StandInStopCursor(self.database)

    def commit(self):
        """Commits nothing.

        Returns:
            None: This method returns nothing.
        """

    def rollback(self):
        """Rolls back nothing.

        Returns:
            None: This method returns nothing.
        """

    def close(self):
        """Closes nothing.

        Returns:
            None: This method returns nothing.
        """


class StandInStopCursor:
    """A cursor that answers the stop slippage statements from the stand-in database.

    Attributes:
        database (StandInStopDatabase): The database.
        answer (list): The rows the last query answered.
    """

    def __init__(self, database):
        """Builds the cursor.

        Args:
            database (StandInStopDatabase): The database.

        Returns:
            None: This method returns nothing.
        """
        self.database = database
        self.answer = []

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            StandInStopCursor: This cursor.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            error_type (type | None): The exception's type.
            error (BaseException | None): The exception.
            traceback (types.TracebackType | None): The traceback.

        Returns:
            bool: False.
        """
        del error_type
        del error
        del traceback
        return False

    def execute(self, statement, parameters=None):
        """Answers or records one statement.

        Args:
            statement (str): The SQL.
            parameters (tuple | None): Its parameters.

        Returns:
            None: This method returns nothing.
        """
        text = statement.strip()
        self.database.statements.append(text.split()[0])
        self.answer = []
        if text.startswith('DELETE'):
            self.database.deleted.append(parameters)
        elif 'FROM unified.synthetic_order_events' in text:
            read_from, read_to = parameters
            for row in self.database.events:
                if read_from <= row['time'] < read_to:
                    values = []
                    for column in EVENT_COLUMNS:
                        values.append(row[column])
                    self.answer.append(tuple(values))
        elif 'FROM unified.instruments' in text:
            for instrument_id in parameters[0]:
                if instrument_id in self.database.segments:
                    self.answer.append((instrument_id, self.database.segments[instrument_id]))
        elif 'FROM unified.stop_slippage' in text:
            self.answer = list(self.database.slips)

    def executemany(self, statement, rows):
        """Records the rows an insert was given.

        Args:
            statement (str): The SQL.
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.database.statements.append(statement.split()[0])
        for row in rows:
            self.database.written.append(list(row))

    def fetchall(self):
        """The rows the last query answered.

        Returns:
            list: The rows.
        """
        return self.answer
