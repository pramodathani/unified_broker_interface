"""Turns the measured execution costs into each broker's typical latency cost and answer time, and writes them to `unified.broker_order_costs`."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)
from unified_broker_interface.utilities.execution_costs.broker_latency import (
    BrokerLatency,
)

DERIVATIVE_SHAPES = [
    'future',
    'option',
]
WINDOW_DAYS = 20

READ_COSTS = """
SELECT
    broker,
    segment,
    product,
    latency_cost_basis_points,
    EXTRACT(EPOCH FROM (answered_at - "time")) * 1000
FROM unified.order_execution_costs
WHERE "time" >= %s
    AND broker IS NOT NULL
"""

UPDATE_COSTS = """
UPDATE unified.broker_order_costs
SET
    latency_cost_bps_intraday = COALESCE(%s, latency_cost_bps_intraday),
    latency_cost_bps_delivery = COALESCE(%s, latency_cost_bps_delivery),
    latency_cost_bps_fno = COALESCE(%s, latency_cost_bps_fno),
    broker_answer_milliseconds = COALESCE(%s, broker_answer_milliseconds),
    latency_calibrated_at = now()
WHERE broker = %s
"""


class LatencyCalibration:
    """Works out each broker's latency cost per order category, and how fast it answers, from `unified.order_execution_costs`.

    The latency cost is how far the mid-price moved against an order while the broker handled it, as basis points of the decision's mid-price. Most legs see no move at all, so a median would almost always be zero; the figure is the mean over every leg, which is the expected cost. A category is measured only with at least `FEWEST_LEGS` (30) legs in the last `WINDOW_DAYS` days, and a figure that cannot be measured keeps what the table already holds.

    The categories match the lowest-cost broker selector's: `fno` for a future or option, `delivery` for a `CNC` order and `intraday` for anything else. Nothing reads the new columns yet; the selector will once enough days have been measured to trust them.

    Attributes:
        connect (callable): Opens a new database connection.
        logger (logging.Logger): The logger.
    """

    def __init__(self, connect, logger):
        """Builds the calibration.

        Args:
            connect (callable): Opens a new psycopg2 database connection.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.connect = connect
        self.logger = logger

    def window_start(self, now, window_days=WINDOW_DAYS):
        """The first moment of the calibration window.

        Args:
            now (datetime.datetime): The moment the calibration runs.
            window_days (int): How many days back the window reaches.

        Returns:
            datetime.datetime: `window_days` days before `now`.
        """
        return now - datetime.timedelta(days=window_days)

    def measure(self, since):
        """Reads every measured leg since a moment and gathers each broker's figures.

        Args:
            since (datetime.datetime): The first moment of the window.

        Returns:
            list: One `BrokerLatency` per broker, by name.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(READ_COSTS, (since,))
                rows = cursor.fetchall()
            connection.rollback()
        finally:
            connection.close()
        return self.brokers_from(rows)

    def brokers_from(self, rows):
        """Gathers rows of the execution cost table into each broker's figures.

        Args:
            rows (list): Tuples of broker (str), segment (str | None), product (str | None), latency cost in basis points (decimal.Decimal | None) and answer time in milliseconds (decimal.Decimal | None).

        Returns:
            list: One `BrokerLatency` per broker, by name.
        """
        brokers = {}
        for broker_name, segment, product, latency_cost, answer_milliseconds in rows:
            broker = brokers.get(broker_name)
            if broker is None:
                broker = BrokerLatency(broker_name)
                brokers[broker_name] = broker
            if latency_cost is not None:
                broker.latency_costs[self.category(segment, product)].append(latency_cost)
            if answer_milliseconds is not None and answer_milliseconds >= 0:
                broker.answer_milliseconds.append(answer_milliseconds)
        ordered = []
        for broker_name in sorted(brokers):
            ordered.append(brokers[broker_name])
        return ordered

    def category(self, segment, product):
        """The selector's category for a leg.

        Args:
            segment (str | None): The instrument's segment, such as `nse_equity_options`.
            product (str | None): The leg's product, such as `CNC`.

        Returns:
            str: `fno` for a future or option, `delivery` for a `CNC` order, and `intraday` otherwise.
        """
        if segment:
            _, _, bare_segment = segment.partition('_')
            if TradeableSegments.SHAPES.get(bare_segment) in DERIVATIVE_SHAPES:
                return 'fno'
        if product == 'CNC':
            return 'delivery'
        return 'intraday'

    def write(self, brokers):
        """Writes every measured figure to `unified.broker_order_costs`, leaving the others as they are.

        Args:
            brokers (list): The `BrokerLatency` figures.

        Returns:
            int: How many brokers' rows were updated.

        Raises:
            psycopg2.Error: When the database cannot be written, after rolling back.
        """
        connection = self.connect()
        updated = 0
        try:
            with connection.cursor() as cursor:
                for broker in brokers:
                    if not broker.measured_anything():
                        continue
                    cursor.execute(
                        UPDATE_COSTS,
                        (
                            broker.latency_cost('intraday'),
                            broker.latency_cost('delivery'),
                            broker.latency_cost('fno'),
                            broker.typical_answer_milliseconds(),
                            broker.broker_name,
                        ),
                    )
                    if cursor.rowcount == 0:
                        self.logger.warning(f'{broker.broker_name} has no row in unified.broker_order_costs, so its latency figures are not kept.')
                    updated = updated + cursor.rowcount
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return updated
