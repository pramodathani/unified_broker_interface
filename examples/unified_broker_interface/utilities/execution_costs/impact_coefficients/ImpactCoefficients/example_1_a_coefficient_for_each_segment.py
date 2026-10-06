"""Looks up the square-root model's coefficient for an option, a currency future and a crude oil future.

The coefficient is kept per asset class, and a segment's asset class comes from the same table the order code uses. The table is seeded with the textbook value of 1.0 for every class; here the commodity row is shown as if it had been fitted, to show how a fitted row reads. This program builds the rows by hand, so it reads no database.

Notice that the currency future has no coefficient because its class has no row, which leaves any estimate that needs the model empty.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/impact_coefficients/ImpactCoefficients/example_1_a_coefficient_for_each_segment.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.impact_coefficients import (
    ImpactCoefficients,
)

SEGMENTS = [
    'nse_equity_index_options',
    'nse_currency_futures',
    'mcx_commodity_futures',
]


class CoefficientForEachSegmentExample:
    """Prints each segment's asset class and coefficient.

    Attributes:
        coefficients (ImpactCoefficients): The coefficients.
    """

    def __init__(self):
        """Builds the coefficients.

        Returns:
            None: This method returns nothing.
        """
        fitted_at = datetime.datetime(2026, 11, 2, tzinfo=datetime.timezone.utc)
        self.coefficients = ImpactCoefficients({
            'securities': (decimal.Decimal('1.0'), None),
            'commodity': (decimal.Decimal('0.65'), fitted_at),
        })

    def run(self):
        """Prints each segment's figures.

        Returns:
            None: This method returns nothing.
        """
        for segment in SEGMENTS:
            print(f'{segment}: class {self.coefficients.asset_class(segment)}, coefficient {self.coefficients.coefficient(segment)}, fitted {self.coefficients.is_fitted(segment)}')


if __name__ == '__main__':
    CoefficientForEachSegmentExample().run()
