"""How far beyond their trigger protective stops have recently filled, per segment and side, read from `unified.stop_slippage`."""

import datetime
import decimal
import math

DEFAULT_WINDOW_DAYS = 20
MINIMUM_STOPS = 30
DEFAULT_PERCENTILE = 90

SLIPS_QUERY = """
SELECT segment, transaction_type, slip_basis_points
FROM unified.stop_slippage
WHERE fired_at >= %s
    AND slip_basis_points IS NOT NULL
ORDER BY segment, transaction_type, slip_basis_points
"""


class StopSlipAllowance:
    """The slip a protective stop should allow for, from how far recent stops in the same segment and on the same side filled beyond their trigger.

    The allowance is a percentile of the measured slips in basis points of the trigger. The 90th percentile, the default, is the slip that nine stops in ten stayed within, so a tripwire placed that far above a floor keeps about nine exits in ten at or above it. A segment and side with fewer than `MINIMUM_STOPS` measured stops has no allowance, because a handful of stops says little about the next one; the tripwire then falls back to the live spread.

    Attributes:
        slips (dict): The measured slips in basis points (decimal.Decimal), each list sorted, keyed by a `(segment, transaction_type)` tuple.
        minimum_stops (int): How many measured stops a segment and side needs before it has an allowance.
    """

    def __init__(self, slips=None, minimum_stops=MINIMUM_STOPS):
        """Builds the allowance from measured slips.

        Args:
            slips (dict | None): Lists of slips in basis points (decimal.Decimal), keyed by a `(segment, transaction_type)` tuple, or None for none.
            minimum_stops (int): How many stops a segment and side needs.

        Returns:
            None: This method returns nothing.
        """
        self.slips = {}
        for key, values in (slips or {}).items():
            self.slips[key] = sorted(values)
        self.minimum_stops = minimum_stops

    def read(self, connect, now, window_days=DEFAULT_WINDOW_DAYS):
        """Replaces the slips held with those of the stops that fired in the last days.

        Args:
            connect (Callable): Opens a PostgreSQL connection, such as `configurations.get_postgres`.
            now (datetime.datetime): The moment to count back from.
            window_days (int): How many days of stops to read.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        since = now - datetime.timedelta(days=window_days)
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(SLIPS_QUERY, (since,))
                fetched = cursor.fetchall()
            connection.rollback()
        finally:
            connection.close()
        slips = {}
        for segment, transaction_type, basis_points in fetched:
            slips.setdefault((segment, transaction_type), []).append(decimal.Decimal(basis_points))
        self.slips = {}
        for key, values in slips.items():
            self.slips[key] = sorted(values)

    def stop_count(self, segment, transaction_type):
        """How many measured stops a segment and side has.

        Args:
            segment (str): The catalogue segment.
            transaction_type (str): `SELL` or `BUY`, the side of the stop's order.

        Returns:
            int: The number of stops.
        """
        return len(self.slips.get((segment, transaction_type), []))

    def percentile(self, values, percentile):
        """The nearest-rank percentile of sorted values.

        Args:
            values (list): Sorted decimal.Decimal values, at least one.
            percentile (int): The percentile, from 1 to 100.

        Returns:
            decimal.Decimal: The smallest value that at least that share of the values are at or below.
        """
        rank = math.ceil(percentile / 100 * len(values))
        return values[max(rank, 1) - 1]

    def basis_points(self, segment, transaction_type, percentile=DEFAULT_PERCENTILE):
        """The allowance in basis points of the trigger.

        Args:
            segment (str): The catalogue segment.
            transaction_type (str): `SELL` or `BUY`.
            percentile (int): Which percentile of the slips to allow for.

        Returns:
            decimal.Decimal | None: The allowance, never below zero, or None when there are too few stops.
        """
        values = self.slips.get((segment, transaction_type), [])
        if len(values) < self.minimum_stops:
            return None
        allowance = self.percentile(values, percentile)
        if allowance < 0:
            return decimal.Decimal(0)
        return allowance

    def fraction(self, segment, transaction_type, percentile=DEFAULT_PERCENTILE):
        """The allowance as a share of the trigger, which the tripwire price takes.

        Args:
            segment (str): The catalogue segment.
            transaction_type (str): `SELL` or `BUY`.
            percentile (int): Which percentile of the slips to allow for.

        Returns:
            decimal.Decimal | None: The share, or None when there are too few stops.
        """
        basis_points = self.basis_points(segment, transaction_type, percentile)
        if basis_points is None:
            return None
        return basis_points / decimal.Decimal(10000)
