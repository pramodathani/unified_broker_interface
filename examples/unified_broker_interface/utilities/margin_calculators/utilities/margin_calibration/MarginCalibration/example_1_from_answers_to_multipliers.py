"""Turns the nine brokers' answers of 2026-09-30 into the exchange's margin and each broker's multipliers.

The calibration takes the exchange's margin for each reference order to be the median of the brokers' answers, because most brokers charge exactly that, and divides each broker's answer by it. A multiplier is rounded to a thousandth and never goes below 1. A category with fewer than three answers is not measured at all. This program feeds in the real answers from that morning's probes, so it calls no broker.

Notice that Flattrade, Shoonya and Wisdom Capital come out above 1 in every category they answered, with Wisdom Capital's intraday at about 1.37, and that crude oil has no figure for Groww, INDmoney or Wisdom Capital.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/margin_calibration/MarginCalibration/example_1_from_answers_to_multipliers.py
"""

import decimal
import logging

from unified_broker_interface.utilities.margin_calculators.utilities.broker_measurement import (
    BrokerMeasurement,
)
from unified_broker_interface.utilities.margin_calculators.utilities.margin_calibration import (
    CATEGORIES,
    MarginCalibration,
)

ANSWERS = [
    ('zerodha', '203.48', '167109.41', '271072.50'),
    ('dhan', '203.54', '167109.40', '271072.50'),
    ('fyers', '204.55', '167171.41', '271100.00'),
    ('groww', '203.40', '167105.13', None),
    ('indmoney', '205.96', '167789.13', None),
    ('kotak', '203.54', '167151.41', '271076.25'),
    ('flattrade', '224.00', '185671.65', '300972.21'),
    ('shoonya', '214.17', '176246.49', '284675.86'),
    ('wisdom_capital', '279.87', '183820.35', None),
]


class FromAnswersToMultipliersExample:
    """Works out the exchange's margins and every broker's multipliers.

    Attributes:
        calibration (MarginCalibration): The calibration, never asked to measure or write.
        measurements (list): The `BrokerMeasurement` results.
    """

    def __init__(self):
        """Builds the calibration and the measurements.

        Returns:
            None: This method returns nothing.
        """
        self.calibration = MarginCalibration(None, logging.getLogger('example'), [])
        self.measurements = []
        for broker_name, intraday, fno, commodity in ANSWERS:
            measurement = BrokerMeasurement(broker_name)
            measurement.margins['intraday'] = decimal.Decimal(intraday)
            measurement.margins['fno'] = decimal.Decimal(fno)
            if commodity is not None:
                measurement.margins['commodity'] = decimal.Decimal(commodity)
            self.measurements.append(measurement)

    def run(self):
        """Prints the exchange's margins, then each broker's multipliers.

        Returns:
            None: This method returns nothing.
        """
        exchange = self.calibration.exchange_margins(self.measurements)
        for category in CATEGORIES:
            print(f'Exchange margin for {category}: {exchange[category]}')
        for measurement in self.measurements:
            multipliers = self.calibration.multipliers(measurement, exchange)
            print(f'{measurement.broker_name}: {multipliers}')
        print(f'With only two brokers: {self.calibration.exchange_margins(self.measurements[:2])}')


if __name__ == '__main__':
    FromAnswersToMultipliersExample().run()
