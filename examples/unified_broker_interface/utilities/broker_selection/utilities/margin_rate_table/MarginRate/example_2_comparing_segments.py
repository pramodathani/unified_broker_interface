"""Compares the fallback margin rates the table is seeded with for four kinds of instrument.

Each segment in `unified.margin_rates` has a row with an empty underlying, which covers every underlying in that segment that has no row of its own. Those rows are deliberately high, because an estimate that is too high only passes over a broker that could have taken the order, while one that is too low sends an order the broker will reject. This program builds four of them and prints how much margin 10 lakh rupees of each would need.

Notice how different the markets are: a currency future needs 7% of its value, an index future 15%, a stock future 40% and a commodity future 47%.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_rate_table/MarginRate/example_2_comparing_segments.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
)


class ComparingSegmentsExample:
    """Prints the margin on the same value in four segments.

    Attributes:
        rows (list): The four `MarginRate` rows.
    """

    def __init__(self):
        """Builds the four fallback rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            MarginRate('nse_currency_futures', '', decimal.Decimal('0.05'), decimal.Decimal('0.02')),
            MarginRate('nse_equity_index_futures', '', decimal.Decimal('0.12'), decimal.Decimal('0.03')),
            MarginRate('nse_equity_futures', '', decimal.Decimal('0.35'), decimal.Decimal('0.05')),
            MarginRate('mcx_commodity_futures', '', decimal.Decimal('0.45'), decimal.Decimal('0.02')),
        ]

    def run(self):
        """Prints each segment's total rate and the margin on 10 lakh rupees.

        Returns:
            None: This method returns nothing.
        """
        value = decimal.Decimal(1000000)
        for margin_rate in self.rows:
            margin = value * margin_rate.total_rate()
            print(f'{margin_rate.segment}: {margin_rate.total_rate()} of the value, {margin:,.0f} on 10 lakh')


if __name__ == '__main__':
    ComparingSegmentsExample().run()
