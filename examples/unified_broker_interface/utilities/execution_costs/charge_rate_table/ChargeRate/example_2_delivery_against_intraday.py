"""Compares what buying and selling a share costs when it is held overnight and when it is traded within the day.

Shares pay different taxes by product: a `CNC` trade, held as delivery, pays STT on both sides and a higher stamp duty, while an intraday trade pays a quarter of the STT and only on the sale. This program builds both NSE rows as seeded, which have not yet been checked against a bill, and prints each side's total.

Notice that a delivery round trip costs more than six times an intraday one.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/charge_rate_table/ChargeRate/example_2_delivery_against_intraday.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)


class DeliveryAgainstIntradayExample:
    """Prints both share rows side by side.

    Attributes:
        rows (list): The delivery and the intraday `ChargeRate`.
    """

    def __init__(self):
        """Builds the two rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            ChargeRate('nse_equities', 'delivery', decimal.Decimal('0.001'), decimal.Decimal('0.001'), decimal.Decimal('0.0000307'), decimal.Decimal('0.000001'), decimal.Decimal('0.00015'), decimal.Decimal('0.18')),
            ChargeRate('nse_equities', 'intraday', decimal.Decimal('0'), decimal.Decimal('0.00025'), decimal.Decimal('0.0000307'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18')),
        ]

    def run(self):
        """Prints each row's buy, sell and round-trip rates as percentages.

        Returns:
            None: This method returns nothing.
        """
        for charge_rate in self.rows:
            buy_side = charge_rate.buy_side_rate() * 100
            sell_side = charge_rate.sell_side_rate() * 100
            checked = charge_rate.checked_on or 'never'
            print(f'{charge_rate.category}: buy {buy_side:.4f}%, sell {sell_side:.4f}%, round trip {buy_side + sell_side:.4f}%, checked {checked}')


if __name__ == '__main__':
    DeliveryAgainstIntradayExample().run()
