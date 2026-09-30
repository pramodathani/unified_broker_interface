"""Measures every broker's margin surcharge and hedge benefit with its own calculator, and writes them to the broker cost table."""

import decimal
import json
import statistics

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.utilities.broker_measurement import (
    BrokerMeasurement,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_orders import (
    ReferenceOrders,
)
from unified_broker_interface.utilities.margin_calculators.utilities.registry import (
    MARGIN_CALCULATOR_CLASSES,
)
from utilities import configurations

CATEGORIES = [
    'intraday',
    'fno',
    'commodity',
]
FEWEST_ANSWERS = 3
LARGEST_MULTIPLIER = decimal.Decimal(3)
THOUSANDTH = decimal.Decimal('0.001')

UPDATE_COSTS = """
UPDATE unified.broker_order_costs
SET
    margin_multiplier_intraday = COALESCE(%s, margin_multiplier_intraday),
    margin_multiplier_fno = COALESCE(%s, margin_multiplier_fno),
    margin_multiplier_commodity = COALESCE(%s, margin_multiplier_commodity),
    gives_hedge_benefit = COALESCE(%s, gives_hedge_benefit),
    margin_calibrated_at = now()
WHERE broker = %s
"""


class MarginCalibration:
    """Asks every broker's calculator about the same reference orders, and turns the answers into each broker's surcharge.

    The exchange's own margin for a reference order is taken to be the median of every broker's answer, because most brokers charge exactly the exchange's margin; on 2026-09-30 six of nine agreed to within half a percent. A broker's multiplier for a category is its answer divided by that median, rounded to a thousandth and never below 1. A category with fewer than three answers is not measured, and a multiplier above 3 is taken to be a misread answer and dropped.

    Hedge benefit is tested with a NIFTY iron condor, priced as a basket and leg by leg at the same broker.

    Only figures that were measured are written; a broker or category that could not be asked keeps what the table already holds.

    Attributes:
        cache (redis.Redis): The Redis client.
        logger (logging.Logger): The logger.
        calculator_classes (list): The `BrokerMarginCalculator` classes to ask.
    """

    def __init__(self, cache, logger, calculator_classes=None):
        """Builds the calibration.

        Args:
            cache (redis.Redis): The Redis client.
            logger (logging.Logger): The logger.
            calculator_classes (list | None): The classes to ask, or None for every broker's.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.logger = logger
        self.calculator_classes = calculator_classes or MARGIN_CALCULATOR_CLASSES

    def calculator(self, calculator_class):
        """A broker's calculator, with the login and settings Redis holds.

        Args:
            calculator_class (type): The broker's `BrokerMarginCalculator` class.

        Returns:
            BrokerMarginCalculator | None: The calculator, or None when Redis holds no login or settings for the broker.
        """
        broker_name = calculator_class.BROKER_NAME
        login_text = self.cache.hget('last_login', broker_name)
        settings_text = self.cache.hget('settings', broker_name)
        if not login_text or not settings_text:
            self.logger.warning(f'{broker_name} has no login or settings in Redis, so its margin calculator is not asked.')
            return None
        return calculator_class(json.loads(login_text), json.loads(settings_text))

    def reference_legs(self, reference_orders):
        """The reference order for each category, and the condor.

        Args:
            reference_orders (ReferenceOrders): The builder.

        Returns:
            tuple: The legs by category (dict of `ReferenceLeg` or None) and the condor's legs (list or None).
        """
        legs = {
            'intraday': reference_orders.intraday_leg(),
            'fno': reference_orders.fno_leg(),
            'commodity': reference_orders.commodity_leg(),
        }
        condor = None
        if legs['fno'] is not None:
            condor = reference_orders.condor_legs(legs['fno'].price)
        return legs, condor

    def measure_broker(self, calculator, legs, condor):
        """Asks one broker about every reference order it can price.

        Args:
            calculator (BrokerMarginCalculator): The broker's calculator.
            legs (dict): The reference leg (or None) by category.
            condor (list | None): The condor's legs.

        Returns:
            BrokerMeasurement: What the broker answered.
        """
        measurement = BrokerMeasurement(calculator.BROKER_NAME)
        for category in CATEGORIES:
            leg = legs.get(category)
            if leg is None or not calculator.takes(leg):
                continue
            try:
                measurement.margins[category] = calculator.order_margin(leg)
            except MarginCalculatorError as error:
                measurement.problems.append(f'{category}: {error}')
        if condor is None or not calculator.TAKES_BASKETS:
            return measurement
        for leg in condor:
            if not calculator.takes(leg):
                return measurement
        try:
            measurement.basket_margin = calculator.basket_margin(condor)
            legs_margin = decimal.Decimal(0)
            for leg in condor:
                legs_margin = legs_margin + calculator.order_margin(leg)
            measurement.legs_margin = legs_margin
        except MarginCalculatorError as error:
            measurement.problems.append(f'condor: {error}')
        return measurement

    def measure(self):
        """Asks every broker that has a login about the reference orders.

        Returns:
            list: One `BrokerMeasurement` per broker asked.

        Raises:
            ValueError: When today's catalogue is not published or no reference order could be built.
        """
        reference_orders = ReferenceOrders(self.cache)
        legs, condor = self.reference_legs(reference_orders)
        built = False
        for leg in legs.values():
            if leg is not None:
                built = True
        if not built:
            raise ValueError('no reference order could be built, because none of INFY, NIFTY futures and crude oil futures has a quote')
        measurements = []
        for calculator_class in self.calculator_classes:
            calculator = self.calculator(calculator_class)
            if calculator is None:
                continue
            measurement = self.measure_broker(calculator, legs, condor)
            for problem in measurement.problems:
                self.logger.warning(f'{calculator_class.BROKER_NAME} {problem}')
            measurements.append(measurement)
        return measurements

    def exchange_margins(self, measurements):
        """The exchange's margin for each category: the median of the brokers' answers.

        Args:
            measurements (list): The `BrokerMeasurement` results.

        Returns:
            dict: The margin (decimal.Decimal, or None when fewer than three brokers answered) by category.
        """
        exchange = {}
        for category in CATEGORIES:
            answers = []
            for measurement in measurements:
                if measurement.margins[category] is not None:
                    answers.append(measurement.margins[category])
            if len(answers) < FEWEST_ANSWERS:
                exchange[category] = None
            else:
                exchange[category] = statistics.median(answers)
        return exchange

    def multipliers(self, measurement, exchange):
        """A broker's surcharge for each category.

        Args:
            measurement (BrokerMeasurement): The broker's answers.
            exchange (dict): The exchange's margin by category.

        Returns:
            dict: The multiplier (decimal.Decimal, or None when not measured) by category.
        """
        multipliers = {}
        for category in CATEGORIES:
            margin = measurement.margins[category]
            reference = exchange[category]
            if margin is None or reference is None or reference <= 0:
                multipliers[category] = None
                continue
            ratio = (margin / reference).quantize(THOUSANDTH, rounding=decimal.ROUND_HALF_UP)
            if ratio > LARGEST_MULTIPLIER:
                multipliers[category] = None
                continue
            multipliers[category] = max(ratio, decimal.Decimal('1.000'))
        return multipliers

    def write(self, measurements, exchange):
        """Writes every measured figure to `unified.broker_order_costs`, leaving the others as they are.

        Args:
            measurements (list): The `BrokerMeasurement` results.
            exchange (dict): The exchange's margin by category.

        Returns:
            int: How many brokers' rows were updated.

        Raises:
            psycopg2.Error: When the database cannot be written.
        """
        connection = configurations.get_postgres()
        updated = 0
        try:
            with connection.cursor() as cursor:
                for measurement in measurements:
                    if not measurement.measured_anything():
                        continue
                    multipliers = self.multipliers(measurement, exchange)
                    cursor.execute(
                        UPDATE_COSTS,
                        (
                            multipliers['intraday'],
                            multipliers['fno'],
                            multipliers['commodity'],
                            measurement.gives_hedge_benefit(),
                            measurement.broker_name,
                        ),
                    )
                    updated = updated + cursor.rowcount
            connection.commit()
        finally:
            connection.close()
        return updated
