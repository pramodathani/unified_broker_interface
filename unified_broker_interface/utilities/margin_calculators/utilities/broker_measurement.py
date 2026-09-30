"""What one broker's margin calculator answered for the reference orders."""

import decimal

HEDGE_SHARE = decimal.Decimal('0.4')


class BrokerMeasurement:
    """One broker's answers: a margin for each category's reference order, and the iron condor priced together and leg by leg.

    Attributes:
        broker_name (str): The broker.
        margins (dict): The margin (decimal.Decimal, or None when not measured) by category: `intraday`, `fno` and `commodity`.
        basket_margin (decimal.Decimal | None): The condor priced as one basket, or None when not measured.
        legs_margin (decimal.Decimal | None): The condor's four legs priced one at a time and added up, or None when not measured.
        problems (list): What went wrong, as messages (str).
    """

    def __init__(self, broker_name):
        """Builds an empty measurement.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.margins = {
            'intraday': None,
            'fno': None,
            'commodity': None,
        }
        self.basket_margin = None
        self.legs_margin = None
        self.problems = []

    def gives_hedge_benefit(self):
        """Whether the broker priced the condor as a hedged whole.

        A hedged condor needs about a quarter of its legs added up. On 2026-09-30 the brokers that gave hedge benefit answered 22% to 25% of the sum, while Fyers answered 59%, a partial offset between its two sold legs but not the spread's defined risk that the selector's estimate relies on. Anything under 40% counts as hedge benefit.

        Returns:
            bool | None: True or False, or None when the condor was not measured both ways.
        """
        if self.basket_margin is None or self.legs_margin is None or self.legs_margin <= 0:
            return None
        return self.basket_margin < self.legs_margin * HEDGE_SHARE

    def measured_anything(self):
        """Whether any figure was measured.

        Returns:
            bool: True when at least one category or the hedge test has an answer.
        """
        for margin in self.margins.values():
            if margin is not None:
                return True
        return self.gives_hedge_benefit() is not None
