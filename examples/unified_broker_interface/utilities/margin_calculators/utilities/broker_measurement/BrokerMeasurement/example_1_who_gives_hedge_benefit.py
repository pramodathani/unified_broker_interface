"""Decides hedge benefit for Zerodha, Shoonya and Fyers from their iron condor answers of 2026-09-30.

A `BrokerMeasurement` holds what one broker's calculator answered. For the hedge test it holds the condor priced as one basket and its four legs priced one at a time and added up. A broker gives hedge benefit when the basket is under 40% of the legs: the brokers that do answered 22% to 25%, while Fyers answered 59%, which offsets its two sold legs a little but does not treat the condor as the defined-risk position it is.

Notice that Fyers is marked False even though its basket is cheaper than its legs.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/broker_measurement/BrokerMeasurement/example_1_who_gives_hedge_benefit.py
"""

import decimal

from unified_broker_interface.utilities.margin_calculators.utilities.broker_measurement import (
    BrokerMeasurement,
)


class WhoGivesHedgeBenefitExample:
    """Builds three measurements and prints their hedge results.

    Attributes:
        measurements (list): The `BrokerMeasurement` results.
    """

    def __init__(self):
        """Builds the measurements from the dry run of 2026-09-30 at 11:35 IST.

        Returns:
            None: This method returns nothing.
        """
        answers = [
            ('zerodha', '66960.20', '306010.77'),
            ('shoonya', '75408.20', '323186.09'),
            ('fyers', '181158.47', '308000.12'),
        ]
        self.measurements = []
        for broker_name, basket_text, legs_text in answers:
            measurement = BrokerMeasurement(broker_name)
            measurement.basket_margin = decimal.Decimal(basket_text)
            measurement.legs_margin = decimal.Decimal(legs_text)
            self.measurements.append(measurement)

    def run(self):
        """Prints each broker's basket as a share of its legs, and the verdict.

        Returns:
            None: This method returns nothing.
        """
        for measurement in self.measurements:
            share = measurement.basket_margin / measurement.legs_margin
            print(f'{measurement.broker_name}: basket is {share:.0%} of the legs, hedge benefit {measurement.gives_hedge_benefit()}')


if __name__ == '__main__':
    WhoGivesHedgeBenefitExample().run()
