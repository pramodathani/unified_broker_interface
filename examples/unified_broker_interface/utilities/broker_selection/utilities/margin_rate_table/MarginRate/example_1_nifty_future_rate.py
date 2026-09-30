"""Builds the NIFTY row of the margin rate table and works out one lot's margin from it.

A `MarginRate` is one row of `unified.margin_rates`: the share of a contract's value the exchange blocks as SPAN (or VaR for an intraday equity order) and as exposure margin. This program builds the NIFTY futures row measured on 2026-09-30, so it needs no database, and multiplies its total rate by the value of one lot at that morning's price.

Notice that the result, about 167,120 rupees, is within 11 rupees of the 167,109.41 that Zerodha, Dhan and Kotak's margin calculators answered for the same lot.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_rate_table/MarginRate/example_1_nifty_future_rate.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
)


class NiftyFutureRateExample:
    """Shows the NIFTY futures rate and one lot's margin.

    Attributes:
        margin_rate (MarginRate): The NIFTY futures row.
    """

    def __init__(self):
        """Builds the row.

        Returns:
            None: This method returns nothing.
        """
        self.margin_rate = MarginRate(
            'nse_equity_index_futures',
            'NIFTY',
            decimal.Decimal('0.0926'),
            decimal.Decimal('0.02'),
        )

    def run(self):
        """Prints the rates and the margin for one lot of 65 at 22,833.70.

        Returns:
            None: This method returns nothing.
        """
        print(f'Segment: {self.margin_rate.segment}')
        print(f'Underlying: {self.margin_rate.underlying}')
        print(f'SPAN rate: {self.margin_rate.span_rate}')
        print(f'Exposure rate: {self.margin_rate.exposure_rate}')
        print(f'Total rate: {self.margin_rate.total_rate()}')
        lot_value = decimal.Decimal('22833.7') * 65
        margin = lot_value * self.margin_rate.total_rate()
        print(f'One lot is worth {lot_value:,.2f}')
        print(f'Estimated margin: {margin:,.2f}')
        print('The brokers answered: 167,109.41')


if __name__ == '__main__':
    NiftyFutureRateExample().run()
