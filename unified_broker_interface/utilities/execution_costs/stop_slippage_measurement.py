"""Follows every protective stop that fired in a range of days to the fill that closed its position, from the order engine's event log, and writes the outcomes to `unified.stop_slippage`."""

import datetime
import decimal
import statistics

from unified_broker_interface.utilities.execution_costs.stop_slip_allowance import (
    StopSlipAllowance,
)
from unified_broker_interface.utilities.execution_costs.stop_outcome import (
    ROW_COLUMNS,
    StopOutcome,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.synthetic_order_event_log import (
    DDL_DIRECTORY,
)

DDL_FILE = '360_unified_stop_slippage.sql'
PARENT_LOOKBACK_DAYS = 1
CLOSE_WINDOW_SECONDS = 60
SUMMARY_PLACES = decimal.Decimal('0.01')

EVENT_COLUMNS = [
    'time',
    'parent_order_id',
    'sequence',
    'event',
    'synthetic_type',
    'leg_id',
    'instrument_id',
    'transaction_type',
    'filled_quantity',
    'average_price',
    'detail',
]

EVENTS_QUERY = """
SELECT
    "time",
    parent_order_id::text,
    sequence,
    event,
    synthetic_type,
    leg_id,
    instrument_id::text,
    transaction_type,
    filled_quantity,
    average_price,
    detail
FROM unified.synthetic_order_events
WHERE "time" >= %s
    AND "time" < %s
    AND event IN ('parent_received', 'parameters_changed', 'leg_requested', 'leg_update')
ORDER BY parent_order_id, sequence
"""

SEGMENTS_QUERY = """
SELECT instrument_id::text, segment
FROM unified.instruments
WHERE instrument_id = ANY(%s::uuid[])
"""

DAILY_ORDERS_TABLE_QUERY = """
SELECT to_regclass('unified.daily_orders') IS NOT NULL
"""

BROKER_FILLS_QUERY = """
SELECT engine_parent_id::text, filled_quantity, average_price
FROM unified.daily_orders
WHERE engine_parent_id = ANY(%s::uuid[])
    AND filled_quantity > 0
    AND average_price IS NOT NULL
"""

DELETE_QUERY = """
DELETE FROM unified.stop_slippage
WHERE fired_at >= %s
    AND fired_at < %s
"""


class StopSlippageMeasurement:
    """Reads the event log for a range of days and works out where each fired protective stop's position was closed.

    A protective stop is a `plan` whose one order has `side` `protect` and a `price_crosses` trigger, which is what every held stop and every routed stop type becomes in the engine. Its side follows its trigger's direction: a stop that fires `at_or_below` sells, and one that fires `at_or_above` buys. It has fired once a `parameters_changed` event shows its trigger fired.

    The close is the stop's own fill when the event log has one. When it has none, the broker's final record of the stop's order in `unified.daily_orders` is read next, because a stop the strategy cancelled just as it filled is a fill the engine never saw: it stops following an order once it is cancelled. Otherwise the close is the first other order on the same instrument and side that was requested within a minute after the stop fired and got a fill, because a strategy whose stop did not fill closes the position itself; those closes are the furthest from the trigger, so leaving them out would make stops look better than they are.

    Attributes:
        connect (Callable): Opens a PostgreSQL connection, such as `configurations.get_postgres`.
        logger (logging.Logger): The logger.
    """

    def __init__(self, connect, logger):
        """Builds the measurement.

        Args:
            connect (Callable): Opens a PostgreSQL connection.
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
        """Follows every protective stop that fired between two moments to its close.

        Args:
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: One `StopOutcome` per fired stop, in the order they fired.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                read_from = start - datetime.timedelta(days=PARENT_LOOKBACK_DAYS)
                read_to = end + datetime.timedelta(seconds=CLOSE_WINDOW_SECONDS)
                cursor.execute(EVENTS_QUERY, (read_from, read_to))
                rows = []
                for values in cursor.fetchall():
                    rows.append(dict(zip(EVENT_COLUMNS, values)))
                parents = self.parents_from(rows)
                outcomes = self.fired_stops(parents, start, end)
                instrument_ids = []
                for outcome in outcomes:
                    if outcome.instrument_id not in instrument_ids:
                        instrument_ids.append(outcome.instrument_id)
                segments = self.read_segments(cursor, instrument_ids)
                parent_order_ids = []
                for outcome in outcomes:
                    parent_order_ids.append(outcome.parent_order_id)
                broker_fills = self.read_broker_fills(cursor, parent_order_ids)
            connection.rollback()
        finally:
            connection.close()
        for outcome in outcomes:
            outcome.segment = segments.get(outcome.instrument_id)
            self.find_close(outcome, parents, broker_fills)
        return outcomes

    def parents_from(self, rows):
        """Folds event rows into one dict per parent order.

        Args:
            rows (list): Event rows as dicts by column name, by parent and then in sequence.

        Returns:
            dict: Each parent order id (str) to a dict with `synthetic_type`, `instrument_id`, `trigger` (the `price_crosses` dict of a protective stop, or None), `fired_at` (datetime.datetime or None) and `legs`, a dict of leg id to a dict with `transaction_type`, `requested_at`, `filled_quantity` and `average_price`.
        """
        parents = {}
        for row in rows:
            parent_order_id = row['parent_order_id']
            parent = parents.get(parent_order_id)
            if parent is None:
                parent = {
                    'synthetic_type': row['synthetic_type'],
                    'instrument_id': row['instrument_id'],
                    'trigger': None,
                    'fired_at': None,
                    'legs': {},
                }
                parents[parent_order_id] = parent
            if row['instrument_id'] and parent['instrument_id'] is None:
                parent['instrument_id'] = row['instrument_id']
            event = row['event']
            if event == 'parent_received':
                parent['trigger'] = self.protective_trigger(row['detail'])
            elif event == 'parameters_changed':
                fired_at = self.fired_at(row)
                if fired_at is not None and parent['fired_at'] is None:
                    parent['fired_at'] = fired_at
            elif event == 'leg_requested':
                parent['legs'][row['leg_id']] = {
                    'transaction_type': row['transaction_type'],
                    'requested_at': row['time'],
                    'filled_quantity': None,
                    'average_price': None,
                }
            elif event == 'leg_update':
                leg = parent['legs'].get(row['leg_id'])
                if leg is not None and row['average_price'] is not None and row['filled_quantity']:
                    leg['filled_quantity'] = row['filled_quantity']
                    leg['average_price'] = row['average_price']
        return parents

    def protective_trigger(self, detail):
        """The trigger of a protective stop, read from its `parent_received` detail.

        Args:
            detail (dict | None): The event's detail.

        Returns:
            dict | None: The `price_crosses` dict, with `field`, `level` and `direction`, or None when the parent is not a protective stop with one.
        """
        if not detail:
            return None
        parameters = detail.get('parameters') or {}
        order = (parameters.get('plan') or {}).get('order')
        if order is None:
            synthetic = (detail.get('body') or {}).get('synthetic') or {}
            order = (synthetic.get('plan') or {}).get('order')
        if not isinstance(order, dict) or order.get('side') != 'protect':
            return None
        trigger = order.get('trigger') or {}
        crosses = trigger.get('price_crosses')
        if not isinstance(crosses, dict) or crosses.get('level') is None:
            return None
        return crosses

    def fired_at(self, row):
        """When a `parameters_changed` event shows a part's trigger had fired.

        Args:
            row (dict): The event row.

        Returns:
            datetime.datetime | None: The part's own `fired_at` when it gives one, the event's time when it only says the trigger fired, or None when it has not fired.
        """
        detail = row['detail'] or {}
        parts = (detail.get('parameters') or {}).get('parts') or {}
        for part in parts.values():
            if not isinstance(part, dict):
                continue
            if part.get('fired_at') is not None:
                return datetime.datetime.fromtimestamp(float(part['fired_at']), INDIA)
            trigger_memory = (part.get('memory') or {}).get('trigger') or {}
            if trigger_memory.get('fired'):
                return row['time']
        return None

    def fired_stops(self, parents, start, end):
        """Builds an outcome for every protective stop that fired between two moments.

        Args:
            parents (dict): The parents `parents_from` built.
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: The `StopOutcome` objects, without their closes, in the order they fired.
        """
        outcomes = []
        for parent_order_id, parent in parents.items():
            trigger = parent['trigger']
            fired_at = parent['fired_at']
            if trigger is None or fired_at is None:
                continue
            if not start <= fired_at < end:
                continue
            if trigger.get('direction') == 'at_or_above':
                transaction_type = 'BUY'
            else:
                transaction_type = 'SELL'
            outcomes.append(StopOutcome(
                parent_order_id,
                parent['instrument_id'],
                None,
                transaction_type,
                trigger.get('field'),
                decimal.Decimal(str(trigger['level'])),
                fired_at,
            ))
        outcomes.sort(key=self.fired_at_of)
        return outcomes

    def fired_at_of(self, outcome):
        """The moment a stop fired, which the outcomes are sorted by.

        Args:
            outcome (StopOutcome): The outcome.

        Returns:
            datetime.datetime: When it fired.
        """
        return outcome.fired_at

    def find_close(self, outcome, parents, broker_fills=None):
        """Records the fill that closed a fired stop's position: its own as the event log or the broker's record has it, or else the first other order's within a minute.

        Args:
            outcome (StopOutcome): The fired stop.
            parents (dict): Every parent `parents_from` built.
            broker_fills (dict | None): The broker's fills of stop orders, as `read_broker_fills` returns them, or None when none were read.

        Returns:
            None: This method returns nothing.
        """
        own = parents[outcome.parent_order_id]
        for leg in own['legs'].values():
            if leg['average_price'] is not None:
                outcome.record_close('stop', leg['filled_quantity'], leg['average_price'])
                return
        broker_fill = (broker_fills or {}).get(outcome.parent_order_id)
        if broker_fill is not None:
            outcome.record_close('stop', broker_fill[0], broker_fill[1])
            return
        latest = outcome.fired_at + datetime.timedelta(seconds=CLOSE_WINDOW_SECONDS)
        best = None
        for parent_order_id, parent in parents.items():
            if parent_order_id == outcome.parent_order_id:
                continue
            if parent['instrument_id'] != outcome.instrument_id:
                continue
            for leg in parent['legs'].values():
                if leg['transaction_type'] != outcome.transaction_type:
                    continue
                if leg['average_price'] is None:
                    continue
                if not outcome.fired_at <= leg['requested_at'] <= latest:
                    continue
                if best is None or leg['requested_at'] < best['requested_at']:
                    best = leg
        if best is not None:
            outcome.record_close('other_order', best['filled_quantity'], best['average_price'])

    def read_broker_fills(self, cursor, parent_order_ids):
        """Reads what the broker's final records say the orders of some parents filled, from `unified.daily_orders`.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            parent_order_ids (list): The parent order ids (str).

        Returns:
            dict: Each parent order id (str) with a fill to a tuple of the filled quantity (int) and the average price (decimal.Decimal) over all its orders; empty when the table does not exist yet.
        """
        if not parent_order_ids:
            return {}
        cursor.execute(DAILY_ORDERS_TABLE_QUERY)
        exists = cursor.fetchall()
        if not exists or not exists[0][0]:
            return {}
        cursor.execute(BROKER_FILLS_QUERY, (parent_order_ids,))
        totals = {}
        for parent_order_id, filled_quantity, average_price in cursor.fetchall():
            quantity, value = totals.get(parent_order_id, (0, decimal.Decimal(0)))
            totals[parent_order_id] = (quantity + filled_quantity, value + filled_quantity * decimal.Decimal(average_price))
        fills = {}
        for parent_order_id, (quantity, value) in totals.items():
            fills[parent_order_id] = (quantity, value / quantity)
        return fills

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

    def write(self, start, end, outcomes):
        """Replaces every row between two moments with the outcomes given, in one transaction, creating the table first if it is missing.

        Args:
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.
            outcomes (list): The `StopOutcome` objects.

        Returns:
            int: How many rows were written.

        Raises:
            psycopg2.Error: When the database cannot be written, after rolling back.
        """
        placeholders = ', '.join(['%s'] * len(ROW_COLUMNS))
        insert = (
            f'INSERT INTO unified.stop_slippage ({", ".join(ROW_COLUMNS)}) '
            f'VALUES ({placeholders})'
        )
        values = []
        for outcome in outcomes:
            row = outcome.row()
            row_values = []
            for column in ROW_COLUMNS:
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

    def summary(self, outcomes):
        """One line of figures per segment and side.

        Args:
            outcomes (list): The `StopOutcome` objects.

        Returns:
            list: Dicts with `segment`, `transaction_type`, `fired`, `by_stop`, `by_other_order`, `unresolved`, and the median and 90th percentile slip in basis points (decimal.Decimal or None), sorted by segment and side.
        """
        groups = {}
        for outcome in outcomes:
            key = (outcome.segment or '', outcome.transaction_type)
            groups.setdefault(key, []).append(outcome)
        lines = []
        for key in sorted(groups):
            group = groups[key]
            slips = []
            by_stop = 0
            by_other_order = 0
            for outcome in group:
                if outcome.closed_by == 'stop':
                    by_stop = by_stop + 1
                elif outcome.closed_by == 'other_order':
                    by_other_order = by_other_order + 1
                basis_points = outcome.slip_basis_points()
                if basis_points is not None:
                    slips.append(basis_points)
            median = None
            ninetieth = None
            if slips:
                median = decimal.Decimal(statistics.median(slips)).quantize(SUMMARY_PLACES)
                ninetieth = StopSlipAllowance().percentile(sorted(slips), 90)
            lines.append({
                'segment': key[0],
                'transaction_type': key[1],
                'fired': len(group),
                'by_stop': by_stop,
                'by_other_order': by_other_order,
                'unresolved': len(group) - by_stop - by_other_order,
                'median_slip_basis_points': median,
                'ninetieth_slip_basis_points': ninetieth,
            })
        return lines
