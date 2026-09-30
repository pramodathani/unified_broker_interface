"""Shows which measurements count as having measured anything, and so which brokers' rows the calibration writes.

The calibration writes a broker's row only when `measured_anything` is true: at least one category has a margin, or the hedge test has an answer. A broker whose every request failed keeps what the table already holds. This program builds four measurements, one of them like INDmoney's, which prices single orders but has no basket calculator and no MCX.

Notice that a broker with only problems is not written, and that the hedge result is None when the condor was priced only one way.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/broker_measurement/BrokerMeasurement/example_2_what_counts_as_measured.py
"""

import decimal

from unified_broker_interface.utilities.margin_calculators.utilities.broker_measurement import (
    BrokerMeasurement,
)


class WhatCountsAsMeasuredExample:
    """Builds four measurements and prints what each holds.

    Attributes:
        measurements (list): The `BrokerMeasurement` results.
    """

    def __init__(self):
        """Builds the measurements.

        Returns:
            None: This method returns nothing.
        """
        failed = BrokerMeasurement('unreachable')
        failed.problems.append('fno: unreachable could not be reached')
        single_orders_only = BrokerMeasurement('indmoney')
        single_orders_only.margins['intraday'] = decimal.Decimal('205.96')
        single_orders_only.margins['fno'] = decimal.Decimal('167789.13')
        basket_only = BrokerMeasurement('half_measured')
        basket_only.basket_margin = decimal.Decimal('75000')
        hedge_only = BrokerMeasurement('hedge_only')
        hedge_only.basket_margin = decimal.Decimal('75000')
        hedge_only.legs_margin = decimal.Decimal('306000')
        self.measurements = [
            failed,
            single_orders_only,
            basket_only,
            hedge_only,
        ]

    def run(self):
        """Prints each measurement's margins, hedge result and whether it would be written.

        Returns:
            None: This method returns nothing.
        """
        for measurement in self.measurements:
            print(f'{measurement.broker_name}: margins {measurement.margins}, hedge {measurement.gives_hedge_benefit()}, '
                  f'written {measurement.measured_anything()}, problems {measurement.problems}')


if __name__ == '__main__':
    WhatCountsAsMeasuredExample().run()
