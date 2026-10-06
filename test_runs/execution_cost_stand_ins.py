"""A stand-in database for measuring execution costs offline, holding scripted engine events, instruments and ticks.

`ExecutionCostMeasurement` sends four kinds of statement: the event query, the segment query, the quote query and, when writing, the table's DDL, a delete and an insert. `LatencyCalibration` reads `unified.order_execution_costs` and updates `unified.broker_order_costs`. `EstimateCheck` reads `unified.impact_coefficients`, the measured legs, five-level books from `unified.ticks` and daily bars from `unified.price_history_adjusted`. The stand-in answers the reads from what a program scripted, choosing the quote the way the real query does, and records the writes, so `python -m test_runs.execution_costs` and the example programs run without PostgreSQL.

Typical usage:

    database = StandInExecutionDatabase()
    database.add_tick(INSTRUMENT, moment, '238.00', '238.50')
    measurement = ExecutionCostMeasurement(database.connect, logger)
"""

import decimal

from unified_broker_interface.utilities.execution_costs.execution_cost_measurement import (
    EVENT_COLUMNS,
)

PRICE_COLUMNS = [
    'price',
    'average_price',
]


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
        cost_rows (list): The scripted rows of `unified.order_execution_costs`, as tuples of broker, segment, product, latency cost in basis points and answer time in milliseconds.
        cost_table_brokers (list): The brokers with a row in `unified.broker_order_costs`.
        updates (list): The parameters of every update of `unified.broker_order_costs`.
        coefficient_rows (list): The scripted rows of `unified.impact_coefficients`, as tuples of asset class, coefficient and fitted_at.
        estimate_legs (list): The scripted measured legs the estimate check reads, as tuples in `LEG_COLUMNS` order.
        books (dict): Each instrument id (str) to a list of tuples of time and the twenty book values the book query returns.
        daily_bars (dict): Each instrument id (str) to a list of tuples of time, close and volume.
        daily_bar_reads (int): How many times daily bars were read.
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
        self.cost_rows = []
        self.cost_table_brokers = []
        self.updates = []
        self.coefficient_rows = []
        self.estimate_legs = []
        self.books = {}
        self.daily_bars = {}
        self.daily_bar_reads = 0

    def add_event(self, time, parent_order_id, event, **columns):
        """Adds one event row, numbering it after the parent's last one.

        Args:
            time (datetime.datetime): When the engine recorded it.
            parent_order_id (str): The parent.
            event (str): The event's name, such as `leg_requested`.
            **columns: Any other column of `EVENT_COLUMNS`, such as `leg_id` or `average_price`; `price` and `average_price` may be given as strings.

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
            if name in PRICE_COLUMNS and value is not None:
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

    def add_book(self, instrument_id, time, bids, asks):
        """Adds one stored five-level book.

        Args:
            instrument_id (str): The instrument.
            time (datetime.datetime): When the tick was received.
            bids (list): Up to five tuples of price (str) and quantity (int), best first.
            asks (list): Up to five tuples of price (str) and quantity (int), best first.

        Returns:
            None: This method returns nothing.
        """
        values = []
        for side in [bids, asks]:
            for level in range(5):
                if level < len(side):
                    values.append(decimal.Decimal(side[level][0]))
                    values.append(side[level][1])
                else:
                    values.append(None)
                    values.append(None)
        self.books.setdefault(instrument_id, []).append((time, values))

    def book_at(self, instrument_id, moment, oldest):
        """The latest stored book after one moment and at or before another, as the real book query chooses it.

        Args:
            instrument_id (str): The instrument.
            moment (datetime.datetime): The latest time allowed.
            oldest (datetime.datetime): The time the book must be after.

        Returns:
            tuple | None: The twenty book values, or None.
        """
        chosen = None
        for time, values in self.books.get(instrument_id, []):
            if values[0] is None or values[10] is None:
                continue
            if time <= oldest or time > moment:
                continue
            if chosen is None or time > chosen[0]:
                chosen = (time, values)
        if chosen is None:
            return None
        return tuple(chosen[1])

    def bars_before(self, instrument_id, before, limit):
        """The latest daily bars before a moment, newest first, as the real daily bar query returns them.

        Args:
            instrument_id (str): The instrument.
            before (datetime.datetime): The moment the bars must be before.
            limit (int): The most bars returned.

        Returns:
            list: Tuples of close and volume.
        """
        bars = []
        for time, close, volume in self.daily_bars.get(instrument_id, []):
            if time < before:
                bars.append((time, close, volume))
        bars.sort(reverse=True)
        answer = []
        for time, close, volume in bars[:limit]:
            answer.append((close, volume))
        return answer

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
        rowcount (int): How many rows the last update changed.
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
        self.rowcount = 0

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
        if 'unified.impact_coefficients' in text:
            self.answer = list(self.database.coefficient_rows)
        elif 'unified.price_history_adjusted' in text:
            self.database.daily_bar_reads = self.database.daily_bar_reads + 1
            self.answer = self.database.bars_before(*parameters)
        elif 'bid5_price' in text:
            self.answer = []
            found = self.database.book_at(*parameters)
            if found is not None:
                self.answer.append(found)
        elif 'decision_mid' in text and 'unified.order_execution_costs' in text:
            self.answer = list(self.database.estimate_legs)
        elif 'unified.synthetic_order_events' in text:
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
        elif text.startswith('SELECT') and 'unified.order_execution_costs' in text:
            self.answer = list(self.database.cost_rows)
        elif text.startswith('UPDATE'):
            self.database.updates.append(parameters)
            self.rowcount = 0
            if parameters[-1] in self.database.cost_table_brokers:
                self.rowcount = 1

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
