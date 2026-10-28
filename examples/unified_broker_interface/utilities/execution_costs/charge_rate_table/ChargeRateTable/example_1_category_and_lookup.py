"""Decides the charge category of three trades and looks up their rows, one of which the table does not hold.

A `ChargeRateTable` holds `unified.charge_rates` in memory. `category` decides which charges a trade pays by the rule the lowest-cost selector prices brokerage by, and `rate` returns the row for a segment and category, or None when the table has none. This program builds the table from rows in memory, the way the offline suites do, so it needs no database.

Notice that an MCX future gets None: its charges are not in the table, so nothing guesses them.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/charge_rate_table/ChargeRateTable/example_1_category_and_lookup.py
"""

import decimal
import logging

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
    ChargeRateTable,
)


class CategoryAndLookupExample:
    """Looks up three trades' rows in a small table.

    Attributes:
        table (ChargeRateTable): The table.
    """

    def __init__(self):
        """Builds the table from two rows.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            ChargeRate('nse_equity_index_options', 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18')),
            ChargeRate('nse_equities', 'delivery', decimal.Decimal('0.001'), decimal.Decimal('0.001'), decimal.Decimal('0.0000307'), decimal.Decimal('0.000001'), decimal.Decimal('0.00015'), decimal.Decimal('0.18')),
        ]
        self.table = ChargeRateTable(logging.getLogger('example'), rows)

    def run(self):
        """Prints the category and the STT on sells found for each trade.

        Returns:
            None: This method returns nothing.
        """
        print(f'Loaded: {self.table.is_loaded()}')
        trades = [
            ('A NIFTY option, NRML', 'nse_equity_index_options', 'derivative', 'NRML'),
            ('A share held overnight, CNC', 'nse_equities', 'security', 'CNC'),
            ('A crude oil future, NRML', 'mcx_commodity_futures', 'derivative', 'NRML'),
        ]
        for name, segment, instrument_kind, product in trades:
            category = self.table.category(instrument_kind, product)
            charge_rate = self.table.rate(segment, category)
            if charge_rate is None:
                print(f'{name}: {category}, no row, so the charges are not known')
                continue
            print(f'{name}: {category}, STT on sells {charge_rate.stt_sell_rate}')


if __name__ == '__main__':
    CategoryAndLookupExample().run()
