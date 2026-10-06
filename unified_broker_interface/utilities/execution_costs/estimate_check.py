"""Compares the pre-trade estimate with what measured orders actually cost, by rebuilding each order's book at the moment it was decided on."""

import datetime
import decimal
import statistics

from unified_broker_interface.utilities.execution_costs.daily_liquidity import (
    DAYS_USED,
    DailyLiquidity,
)
from unified_broker_interface.utilities.execution_costs.impact_coefficients import (
    ImpactCoefficients,
)
from unified_broker_interface.utilities.execution_costs.pre_trade_estimate import (
    PreTradeEstimate,
)

MAXIMUM_QUOTE_AGE_SECONDS = 60
BASIS_POINTS = decimal.Decimal(10000)
HUNDREDTH = decimal.Decimal('0.01')
LEVELS = 5
STOP_ORDER_TYPES = [
    'SL',
    'SL-M',
]

LEG_COLUMNS = [
    'parent_order_id',
    'leg_id',
    'broker',
    'instrument_id',
    'segment',
    'transaction_type',
    'order_type',
    'price',
    'filled_quantity',
    'decided_at',
    'decision_mid',
    'half_spread_cost',
    'beyond_touch_cost',
]

READ_LEGS = """
SELECT
    parent_order_id::text,
    leg_id,
    broker,
    instrument_id::text,
    segment,
    transaction_type,
    order_type,
    price,
    filled_quantity,
    decided_at,
    decision_mid,
    half_spread_cost,
    beyond_touch_cost
FROM unified.order_execution_costs
WHERE "time" >= %s
    AND "time" < %s
    AND half_spread_cost IS NOT NULL
    AND beyond_touch_cost IS NOT NULL
    AND decision_mid > 0
ORDER BY "time"
"""

READ_BOOK = """
SELECT
    bid1_price, bid1_quantity, bid2_price, bid2_quantity, bid3_price, bid3_quantity,
    bid4_price, bid4_quantity, bid5_price, bid5_quantity,
    ask1_price, ask1_quantity, ask2_price, ask2_quantity, ask3_price, ask3_quantity,
    ask4_price, ask4_quantity, ask5_price, ask5_quantity
FROM unified.ticks
WHERE instrument_id = %s
    AND "time" <= %s
    AND "time" > %s
    AND bid1_price > 0
    AND ask1_price > 0
ORDER BY "time" DESC
LIMIT 1
"""

READ_DAILY_BARS = """
SELECT close, volume
FROM unified.price_history_adjusted
WHERE instrument_id = %s
    AND "interval" = 'day'
    AND "time" < %s
ORDER BY "time" DESC
LIMIT %s
"""


class EstimateCheck:
    """Runs the pre-trade estimate on every measured leg and sets it beside what the leg actually cost.

    For each leg in `unified.order_execution_costs`, the five-level book at the decision moment is read back from `unified.ticks`, the instrument's daily volatility and volume from the daily bars before that day, and the coefficient from `unified.impact_coefficients`. The estimate is the cost of crossing the spread for the filled quantity. What the leg actually cost on the same footing is its `half_spread_cost` plus `beyond_touch_cost`, which leave out the price moving before and during sending.

    An estimate of crossing the spread is only a fair prediction for a leg that did cross it, so legs are split into crossing ones (a market order, or a limit at or through the other side's best price at the decision) and resting ones, and the two are summarised apart. A stop order is always resting: it waits for its trigger and fills later, against a book the decision never saw. A limit order whose book is missing counts as resting too, because it cannot be shown to have crossed.

    Attributes:
        connect (callable): Opens a new database connection.
        logger (logging.Logger): The logger.
        coefficients (ImpactCoefficients): The coefficients, read when the check runs.
        liquidity_cache (dict): Each (instrument id, date) to its `DailyLiquidity`, so one instrument's bars are read once a day.
    """

    def __init__(self, connect, logger):
        """Builds the check.

        Args:
            connect (callable): Opens a new psycopg2 database connection.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.connect = connect
        self.logger = logger
        self.coefficients = ImpactCoefficients()
        self.liquidity_cache = {}

    def compare(self, start, end):
        """Compares the estimate with the actual cost of every measured leg sent between two moments.

        Args:
            start (datetime.datetime): The first moment, inclusive.
            end (datetime.datetime): The last moment, exclusive.

        Returns:
            list: One dict per leg with `leg` (the row as a dict), `crossing` (bool), `covered_by_book` (bool | None), `estimated_basis_points` and `actual_basis_points` (decimal.Decimal | None); a leg with no book at its decision has None for both figures.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = self.connect()
        comparisons = []
        try:
            with connection.cursor() as cursor:
                self.coefficients.load(cursor)
                cursor.execute(READ_LEGS, (start, end))
                legs = []
                for values in cursor.fetchall():
                    legs.append(dict(zip(LEG_COLUMNS, values)))
                for leg in legs:
                    comparisons.append(self.compare_leg(cursor, leg))
            connection.rollback()
        finally:
            connection.close()
        return comparisons

    def compare_leg(self, cursor, leg):
        """Estimates one leg from its decision-time book and sets it beside its actual cost.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            leg (dict): One row of the legs query, by column name.

        Returns:
            dict: The comparison, as `compare` describes it.
        """
        actual = (leg['half_spread_cost'] + leg['beyond_touch_cost']) / leg['decision_mid'] * BASIS_POINTS
        comparison = {
            'leg': leg,
            'crossing': leg['order_type'] == 'MARKET',
            'covered_by_book': None,
            'estimated_basis_points': None,
            'actual_basis_points': actual.quantize(HUNDREDTH),
        }
        book = self.book_at(cursor, leg['instrument_id'], leg['decided_at'])
        if book is None:
            return comparison
        bids, asks = book
        liquidity = self.liquidity_before(cursor, leg['instrument_id'], leg['decided_at'])
        estimate = PreTradeEstimate(
            leg['transaction_type'],
            leg['filled_quantity'],
            bids,
            asks,
            liquidity,
            self.coefficients.coefficient(leg['segment']),
        )
        comparison['crossing'] = self.is_crossing(leg, bids, asks)
        comparison['covered_by_book'] = estimate.is_covered_by_book()
        comparison['estimated_basis_points'] = estimate.basis_points()
        return comparison

    def is_crossing(self, leg, bids, asks):
        """Whether a leg would trade at once against the book at its decision: a market order, or a limit at or through the other side's best price; never a stop order.

        Args:
            leg (dict): The leg, with `order_type`, `transaction_type` and `price`.
            bids (list): The bid levels, best first.
            asks (list): The ask levels, best first.

        Returns:
            bool: True for a crossing leg.
        """
        if leg['order_type'] in STOP_ORDER_TYPES:
            return False
        if leg['order_type'] == 'MARKET' or leg['price'] is None:
            return True
        if leg['transaction_type'] == 'SELL':
            return bool(bids) and leg['price'] <= bids[0][0]
        return bool(asks) and leg['price'] >= asks[0][0]

    def book_at(self, cursor, instrument_id, moment):
        """The latest five-level book with both sides at or before a moment, if it is recent enough.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            instrument_id (str): The instrument.
            moment (datetime.datetime): The moment.

        Returns:
            tuple | None: The bids and the asks, each a list of tuples of price and quantity, best first; or None when there is no tick within `MAXIMUM_QUOTE_AGE_SECONDS`.
        """
        oldest = moment - datetime.timedelta(seconds=MAXIMUM_QUOTE_AGE_SECONDS)
        cursor.execute(READ_BOOK, (instrument_id, moment, oldest))
        found = cursor.fetchone()
        if found is None:
            return None
        bids = []
        asks = []
        for level in range(LEVELS):
            bids.append((found[2 * level], found[2 * level + 1]))
            asks.append((found[2 * LEVELS + 2 * level], found[2 * LEVELS + 2 * level + 1]))
        return bids, asks

    def liquidity_before(self, cursor, instrument_id, moment):
        """The instrument's daily volatility and volume from the daily bars before the day of a moment, read once per instrument and day.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            instrument_id (str): The instrument.
            moment (datetime.datetime): The moment; only bars before its day are used.

        Returns:
            DailyLiquidity: The figures, which may be None inside when there are too few bars.
        """
        day = moment.date()
        key = (instrument_id, day)
        if key not in self.liquidity_cache:
            day_start = datetime.datetime.combine(day, datetime.time(), moment.tzinfo)
            cursor.execute(READ_DAILY_BARS, (instrument_id, day_start, DAYS_USED + 1))
            closes = []
            volumes = []
            for close, volume in reversed(cursor.fetchall()):
                closes.append(close)
                volumes.append(volume)
            self.liquidity_cache[key] = DailyLiquidity(closes, volumes)
        return self.liquidity_cache[key]

    def summary(self, comparisons):
        """The crossing and resting legs' figures side by side.

        Args:
            comparisons (list): The dicts `compare` returns.

        Returns:
            list: Two dicts, for `crossing` and `resting`, each with `legs`, `estimated` (legs with an estimate), `beyond_book` (legs the visible book did not cover), `mean_estimated_basis_points`, `mean_actual_basis_points` and `mean_absolute_difference`, the means being None without estimated legs.
        """
        lines = []
        for name in ['crossing', 'resting']:
            wanted = name == 'crossing'
            estimated = []
            actual = []
            differences = []
            leg_count = 0
            beyond_book = 0
            for comparison in comparisons:
                if comparison['crossing'] != wanted:
                    continue
                leg_count = leg_count + 1
                if comparison['covered_by_book'] is False:
                    beyond_book = beyond_book + 1
                if comparison['estimated_basis_points'] is None:
                    continue
                estimated.append(comparison['estimated_basis_points'])
                actual.append(comparison['actual_basis_points'])
                differences.append(abs(comparison['estimated_basis_points'] - comparison['actual_basis_points']))
            lines.append({
                'kind': name,
                'legs': leg_count,
                'estimated': len(estimated),
                'beyond_book': beyond_book,
                'mean_estimated_basis_points': self.mean(estimated),
                'mean_actual_basis_points': self.mean(actual),
                'mean_absolute_difference': self.mean(differences),
            })
        return lines

    def mean(self, values):
        """The mean of some figures, rounded to a hundredth.

        Args:
            values (list): The figures (decimal.Decimal).

        Returns:
            decimal.Decimal | None: The mean, or None for no figures.
        """
        if not values:
            return None
        return decimal.Decimal(statistics.mean(values)).quantize(HUNDREDTH)
