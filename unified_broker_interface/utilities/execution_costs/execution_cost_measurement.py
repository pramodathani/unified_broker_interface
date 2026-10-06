"""Works out what every filled leg of a range of days cost, from the order engine's event log and the stored tick history, and writes it to `unified.order_execution_costs`."""

import datetime
import decimal
import statistics

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)
from unified_broker_interface.utilities.execution_costs.execution_cost import (
    ExecutionCost,
)
from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)
from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.synthetic_order_event_log import (
    DDL_DIRECTORY,
)

DDL_FILE = '350_unified_order_execution_costs.sql'
MAXIMUM_QUOTE_AGE_SECONDS = 60
PARENT_LOOKBACK_DAYS = 30
SUMMARY_PLACES = decimal.Decimal('0.01')

EVENT_COLUMNS = [
    'time',
    'parent_order_id',
    'sequence',
    'event',
    'synthetic_type',
    'leg_id',
    'leg_role',
    'broker',
    'instrument_id',
    'transaction_type',
    'product',
    'order_type',
    'quantity',
    'price',
    'filled_quantity',
    'average_price',
    'outcome',
]

COST_COLUMNS = [
    'time',
    'parent_order_id',
    'leg_id',
    'synthetic_type',
    'leg_role',
    'broker',
    'instrument_id',
    'segment',
    'transaction_type',
    'product',
    'order_type',
    'quantity',
    'price',
    'filled_quantity',
    'average_price',
    'decided_at',
    'answered_at',
    'decision_quote_time',
    'send_quote_time',
    'answer_quote_time',
    'decision_mid',
    'send_mid',
    'answer_mid',
    'delay_cost',
    'latency_cost',
    'half_spread_cost',
    'beyond_touch_cost',
    'total_cost',
    'total_cost_basis_points',
    'latency_cost_basis_points',
    'total_cost_rupees',
]

EVENTS_QUERY = """
SELECT
    "time",
    parent_order_id::text,
    sequence,
    event,
    synthetic_type,
    leg_id,
    leg_role,
    broker,
    instrument_id::text,
    transaction_type,
    product,
    order_type,
    quantity,
    price,
    filled_quantity,
    average_price,
    outcome
FROM unified.synthetic_order_events
WHERE parent_order_id IN (
    SELECT DISTINCT parent_order_id
    FROM unified.synthetic_order_events
    WHERE event = 'leg_requested'
        AND "time" >= %s
        AND "time" < %s
)
    AND event IN ('parent_received', 'leg_requested', 'leg_answered', 'leg_update')
    AND "time" >= %s
ORDER BY parent_order_id, sequence
"""

SEGMENTS_QUERY = """
SELECT instrument_id::text, segment
FROM unified.instruments
WHERE instrument_id = ANY(%s::uuid[])
"""

QUOTE_QUERY = """
SELECT "time", bid1_price, ask1_price
FROM unified.ticks
WHERE instrument_id = %s
    AND "time" <= %s
    AND "time" > %s
    AND bid1_price > 0
    AND ask1_price > 0
ORDER BY "time" DESC
LIMIT 1
"""

DELETE_QUERY = """
DELETE FROM unified.order_execution_costs
WHERE "time" >= %s
    AND "time" < %s
"""


class ExecutionCostMeasurement:
    """Measures the execution cost of every leg the order engine sent and got a fill for, over whole days in India's time zone.

    Nothing here touches the order path. The engine already logs when each parent arrived, when each leg was sent and answered, and every fill; the quotes at those moments are read back from `unified.ticks`. A quote older than `MAXIMUM_QUOTE_AGE_SECONDS` at the moment it stands for is treated as missing, which leaves the parts that need it empty.

    Attributes:
        connect (callable): Opens a new database connection.
        logger (logging.Logger): The logger.
    """

    def __init__(self, connect, logger):
        """Builds the measurement.

        Args:
            connect (callable): Opens a new psycopg2 database connection.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.connect = connect
        self.logger = logger

    def day_bounds(self, last_day, day_count):
        """The start and end of a run of whole days in India's time zone.

        Args:
            last_day (datetime.date): The last day measured.
            day_count (int): How many days, ending with `last_day`.

        Returns:
            tuple: The start (datetime.datetime) and the end (datetime.datetime), the end being midnight after `last_day`.
        """
        first_day = last_day - datetime.timedelta(days=day_count - 1)
        start = datetime.datetime.combine(first_day, datetime.time(), INDIA)
        end = datetime.datetime.combine(
            last_day + datetime.timedelta(days=1),
            datetime.time(),
            INDIA,
        )
        return start, end

    def measure(self, start, end):
        """Measures every leg sent between two moments that got a fill.

        Args:
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: One `ExecutionCost` per filled leg, in the order the legs were sent.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                rows = self.read_events(cursor, start, end)
                legs = self.filled_legs(rows, start, end)
                instrument_ids = []
                for leg in legs:
                    if leg.instrument_id not in instrument_ids:
                        instrument_ids.append(leg.instrument_id)
                segments = self.read_segments(cursor, instrument_ids)
                costs = []
                for leg in legs:
                    costs.append(self.cost_of(cursor, leg, segments.get(leg.instrument_id)))
            connection.rollback()
        finally:
            connection.close()
        return costs

    def read_events(self, cursor, start, end):
        """Reads every event that matters of every parent with a leg sent between two moments.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: The rows as dicts by column name, by parent and then in sequence.
        """
        lookback_start = start - datetime.timedelta(days=PARENT_LOOKBACK_DAYS)
        cursor.execute(EVENTS_QUERY, (start, end, lookback_start))
        rows = []
        for values in cursor.fetchall():
            rows.append(dict(zip(EVENT_COLUMNS, values)))
        return rows

    def filled_legs(self, rows, start, end):
        """Folds event rows into legs and keeps the ones sent between two moments that got a fill.

        The first leg a parent sends is measured from the parent's arrival, so the time a held or conditional order waited counts as delay. Every later leg, such as a stop placed after a fill, is measured from its own request.

        Args:
            rows (list): Event rows as dicts, by parent and then in sequence.
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: The `LegExecution` objects, in the order they were sent.
        """
        received_at = {}
        parents_with_a_leg = set()
        legs = {}
        for row in rows:
            parent_order_id = row['parent_order_id']
            if row['event'] == 'parent_received':
                received_at[parent_order_id] = row['time']
                continue
            key = (parent_order_id, row['leg_id'])
            leg = legs.get(key)
            if leg is None:
                if row['event'] != 'leg_requested':
                    continue
                decided_at = row['time']
                if parent_order_id not in parents_with_a_leg:
                    parents_with_a_leg.add(parent_order_id)
                    decided_at = received_at.get(parent_order_id, row['time'])
                leg = LegExecution(parent_order_id, row['leg_id'], decided_at)
                legs[key] = leg
            leg.apply(row)
        kept = []
        for leg in legs.values():
            if leg.is_filled() and start <= leg.sent_at < end:
                kept.append(leg)
        kept.sort(key=self.sent_at_of)
        return kept

    def sent_at_of(self, leg):
        """The moment a leg was sent, which the legs are sorted by.

        Args:
            leg (LegExecution): The leg.

        Returns:
            datetime.datetime: When it was sent.
        """
        return leg.sent_at

    def read_segments(self, cursor, instrument_ids):
        """Reads the segment of each instrument.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            instrument_ids (list): The instrument ids (str).

        Returns:
            dict: Each instrument id (str) to its segment (str); an instrument not in `unified.instruments` is left out.
        """
        if not instrument_ids:
            return {}
        cursor.execute(SEGMENTS_QUERY, (instrument_ids,))
        segments = {}
        for instrument_id, segment in cursor.fetchall():
            segments[instrument_id] = segment
        return segments

    def cost_of(self, cursor, leg, segment):
        """Reads the three quotes one leg is measured against and builds its cost.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            leg (LegExecution): The filled leg.
            segment (str | None): The instrument's segment, or None when it is not known.

        Returns:
            ExecutionCost: The leg's cost.
        """
        at_decision = self.quote_at(cursor, leg.instrument_id, leg.decided_at)
        at_send = self.quote_at(cursor, leg.instrument_id, leg.sent_at)
        at_answer = None
        if leg.answered_at is not None:
            at_answer = self.quote_at(cursor, leg.instrument_id, leg.answered_at)
        return ExecutionCost(
            leg,
            at_decision,
            at_send,
            at_answer,
            segment,
            self.is_securities_market(segment),
        )

    def quote_at(self, cursor, instrument_id, moment):
        """The latest stored quote with both sides of the book at or before a moment, if it is recent enough.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            instrument_id (str): The instrument.
            moment (datetime.datetime): The moment the quote stands for.

        Returns:
            QuoteMoment | None: The quote, or None when there is none within `MAXIMUM_QUOTE_AGE_SECONDS`.
        """
        oldest = moment - datetime.timedelta(seconds=MAXIMUM_QUOTE_AGE_SECONDS)
        cursor.execute(QUOTE_QUERY, (instrument_id, moment, oldest))
        found = cursor.fetchone()
        if found is None:
            return None
        return QuoteMoment(found[0], found[1], found[2])

    def is_securities_market(self, segment):
        """Whether a segment is in the securities markets, where every broker reports quantities in units.

        Args:
            segment (str | None): A segment such as `nse_equity_options`.

        Returns:
            bool: True for equities, fixed income, funds and their derivatives.
        """
        if not segment:
            return False
        _, _, bare_segment = segment.partition('_')
        return TradeableSegments.ASSET_CLASSES.get(bare_segment) == 'securities'

    def write(self, start, end, costs):
        """Replaces every row between two moments with the costs given, in one transaction, creating the table first if it is missing.

        Args:
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.
            costs (list): The `ExecutionCost` objects.

        Returns:
            int: How many rows were written.

        Raises:
            psycopg2.Error: When the database cannot be written, after rolling back.
        """
        placeholders = ', '.join(['%s'] * len(COST_COLUMNS))
        insert = (
            f'INSERT INTO unified.order_execution_costs ({", ".join(COST_COLUMNS)}) '
            f'VALUES ({placeholders})'
        )
        values = []
        for cost in costs:
            row = cost.row()
            row_values = []
            for column in COST_COLUMNS:
                row_values.append(row[column])
            values.append(row_values)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute((DDL_DIRECTORY / DDL_FILE).read_text())
                cursor.execute(DELETE_QUERY, (start, end))
                if values:
                    cursor.executemany(insert, values)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return len(values)

    def summary(self, costs):
        """Each broker's legs and median costs, for a person to read.

        Args:
            costs (list): The `ExecutionCost` objects.

        Returns:
            list: One dict per broker, by name, with `broker`, `legs`, `measured` (legs with a decision quote), `median_total_basis_points`, `mean_total_basis_points` and `mean_latency_basis_points`, each figure being None without any legs to work it out from.
        """
        totals = {}
        latencies = {}
        leg_counts = {}
        for cost in costs:
            broker = cost.leg.broker
            leg_counts[broker] = leg_counts.get(broker, 0) + 1
            totals.setdefault(broker, [])
            latencies.setdefault(broker, [])
            total = cost.basis_points(cost.total())
            if total is not None:
                totals[broker].append(total)
            latency = cost.basis_points(cost.latency())
            if latency is not None:
                latencies[broker].append(latency)
        lines = []
        for broker in sorted(leg_counts):
            lines.append({
                'broker': broker,
                'legs': leg_counts[broker],
                'measured': len(totals[broker]),
                'median_total_basis_points': self.median(totals[broker]),
                'mean_total_basis_points': self.mean(totals[broker]),
                'mean_latency_basis_points': self.mean(latencies[broker]),
            })
        return lines

    def median(self, values):
        """The median of some figures, rounded to a hundredth.

        Args:
            values (list): The figures (decimal.Decimal).

        Returns:
            decimal.Decimal | None: The median, or None for no figures.
        """
        if not values:
            return None
        return decimal.Decimal(statistics.median(values)).quantize(SUMMARY_PLACES)

    def mean(self, values):
        """The mean of some figures, rounded to a hundredth.

        The mean is shown beside the median because most legs see no change in the mid-price while a broker answers, so a median latency is nearly always zero and hides a broker that is occasionally slow.

        Args:
            values (list): The figures (decimal.Decimal).

        Returns:
            decimal.Decimal | None: The mean, or None for no figures.
        """
        if not values:
            return None
        return decimal.Decimal(statistics.mean(values)).quantize(SUMMARY_PLACES)
