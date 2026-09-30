"""Looks up margin rates for three underlyings, two of which have no row of their own.

A `MarginRateTable` holds `unified.margin_rates` in memory. `rate` first looks for a row naming the segment and the underlying, then for the segment's own row with an empty underlying, and returns None when neither exists. This program builds the table from rows in memory, the way the offline suites do, so it needs no database.

Notice that NIFTY gets its measured rate, BANKNIFTY falls back to the cautious index rate, and a mutual fund, which has no row at all, gets None. The margin estimate charges an instrument with no rate its whole value.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_rate_table/MarginRateTable/example_1_underlying_and_fallback.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)


class UnderlyingAndFallbackExample:
    """Looks up three rates in a small table.

    Attributes:
        table (MarginRateTable): The table.
    """

    def __init__(self):
        """Builds the table from two rows.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            MarginRate('nse_equity_index_futures', '', decimal.Decimal('0.12'), decimal.Decimal('0.03')),
            MarginRate('nse_equity_index_futures', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
        ]
        self.table = MarginRateTable(logging.getLogger('example'), rows)

    def run(self):
        """Prints the rate found for each lookup.

        Returns:
            None: This method returns nothing.
        """
        print(f'Loaded: {self.table.is_loaded()}')
        lookups = [
            ('nse_equity_index_futures', 'NIFTY'),
            ('nse_equity_index_futures', 'BANKNIFTY'),
            ('nse_mutual_funds', None),
        ]
        for segment, underlying in lookups:
            margin_rate = self.table.rate(segment, underlying)
            if margin_rate is None:
                print(f'{segment} {underlying}: no rate')
                continue
            print(f'{segment} {underlying}: {margin_rate.total_rate()} from the row for {margin_rate.underlying or "every underlying"}')


if __name__ == '__main__':
    UnderlyingAndFallbackExample().run()
