"""Builds the NSE index option row checked against Flattrade's bill of 19 October 2026 and shows what each side of a trade pays.

A `ChargeRate` is one row of `unified.charge_rates`: STT, the exchange's charge, SEBI's fee, stamp duty and GST, each as a share of the value traded. `buy_side_rate` and `sell_side_rate` add up everything one side pays, with GST on the exchange charge and the SEBI fee but not on STT or stamp duty.

Notice that selling costs more than four times what buying does, because STT on an option is charged only on the sale.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/charge_rate_table/ChargeRate/example_1_option_side_rates.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)


class OptionSideRatesExample:
    """Shows the option row's rates and what each side pays.

    Attributes:
        charge_rate (ChargeRate): The NSE index option row.
    """

    def __init__(self):
        """Builds the row.

        Returns:
            None: This method returns nothing.
        """
        self.charge_rate = ChargeRate(
            'nse_equity_index_options',
            'fno',
            decimal.Decimal('0'),
            decimal.Decimal('0.0015'),
            decimal.Decimal('0.0003553'),
            decimal.Decimal('0.000001'),
            decimal.Decimal('0.00003'),
            decimal.Decimal('0.18'),
            datetime.date(2026, 10, 19),
        )

    def run(self):
        """Prints the rates and each side's total as a percentage of the premium.

        Returns:
            None: This method returns nothing.
        """
        print(f'Segment: {self.charge_rate.segment} ({self.charge_rate.category})')
        print(f'Checked against a bill on: {self.charge_rate.checked_on}')
        print(f'STT on sells: {self.charge_rate.stt_sell_rate}')
        print(f'Exchange charge on each side: {self.charge_rate.exchange_rate}')
        buy_side = self.charge_rate.buy_side_rate() * 100
        sell_side = self.charge_rate.sell_side_rate() * 100
        print(f'Buying pays {buy_side:.4f}% of the premium')
        print(f'Selling pays {sell_side:.4f}% of the premium')
        print(f'A round trip pays {buy_side + sell_side:.4f}%')


if __name__ == '__main__':
    OptionSideRatesExample().run()
