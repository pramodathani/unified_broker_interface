"""One broker's latency figures over the calibration window, gathered from `unified.order_execution_costs`."""

import decimal
import statistics

CATEGORIES = [
    'intraday',
    'delivery',
    'fno',
]
FEWEST_LEGS = 30
HUNDREDTH = decimal.Decimal('0.01')
WHOLE = decimal.Decimal('1')


class BrokerLatency:
    """One broker's latency figures over the calibration window.

    Attributes:
        broker_name (str): The broker.
        latency_costs (dict): The latency cost in basis points (decimal.Decimal) of every measured leg, as a list for each category.
        answer_milliseconds (list): How long the broker took to answer each leg, in milliseconds (decimal.Decimal).
    """

    def __init__(self, broker_name):
        """Builds a broker's figures with no legs yet.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.latency_costs = {}
        for category in CATEGORIES:
            self.latency_costs[category] = []
        self.answer_milliseconds = []

    def leg_count(self, category):
        """How many legs of one category have a latency cost.

        Args:
            category (str): `intraday`, `delivery` or `fno`.

        Returns:
            int: The count.
        """
        return len(self.latency_costs[category])

    def latency_cost(self, category):
        """The expected latency cost of one category: the mean over every leg.

        Most legs see no move in the mid-price while the broker handles them, and the cost comes from the few that do, so every leg is kept; dropping the extremes would drop the cost itself.

        Args:
            category (str): `intraday`, `delivery` or `fno`.

        Returns:
            decimal.Decimal | None: Basis points, rounded to a hundredth, or None with fewer than `FEWEST_LEGS` legs.
        """
        values = self.latency_costs[category]
        if len(values) < FEWEST_LEGS:
            return None
        mean = decimal.Decimal(statistics.mean(values)).quantize(HUNDREDTH)
        if mean == 0:
            return abs(mean)
        return mean

    def typical_answer_milliseconds(self):
        """The median time the broker took to answer.

        Returns:
            decimal.Decimal | None: Milliseconds, rounded to a whole number, or None with fewer than `FEWEST_LEGS` answers.
        """
        if len(self.answer_milliseconds) < FEWEST_LEGS:
            return None
        median = decimal.Decimal(statistics.median(self.answer_milliseconds))
        return median.quantize(WHOLE)

    def measured_anything(self):
        """Whether any figure has enough legs behind it to be written.

        Returns:
            bool: True when at least one figure is not None.
        """
        if self.typical_answer_milliseconds() is not None:
            return True
        for category in CATEGORIES:
            if self.latency_cost(category) is not None:
                return True
        return False
