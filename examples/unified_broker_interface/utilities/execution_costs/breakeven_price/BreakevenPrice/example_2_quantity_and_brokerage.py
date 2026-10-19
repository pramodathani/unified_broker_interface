"""Shows how flat brokerage pushes the breakeven away from the entry, most of all for a small quantity, and how a sold position's breakeven sits below its entry.

Brokerage is charged per order, not per unit, so `BreakevenPrice` shares it across the position's quantity. This program prices shares bought intraday at 500.00 with 20 rupees an order, in four quantities, and then a NIFTY option sold at 177.00.

Notice that one share must rise almost 10% to break even, while a thousand need only 0.05%.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_price/BreakevenPrice/example_2_quantity_and_brokerage.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)


class QuantityAndBrokerageExample:
    """Prints breakevens for several quantities and for a sold option.

    Attributes:
        intraday_rate (ChargeRate): The NSE intraday share row.
        option_rate (ChargeRate): The NSE index option row.
    """

    def __init__(self):
        """Builds the two rows.

        Returns:
            None: This method returns nothing.
        """
        self.intraday_rate = ChargeRate('nse_equities', 'intraday', decimal.Decimal('0'), decimal.Decimal('0.00025'), decimal.Decimal('0.0000307'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))
        self.option_rate = ChargeRate('nse_equity_index_options', 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))

    def run(self):
        """Prints each breakeven and how far it is from the entry.

        Returns:
            None: This method returns nothing.
        """
        entry = decimal.Decimal('500.00')
        for quantity in (1, 10, 100, 1000):
            breakeven = BreakevenPrice(self.intraday_rate, 'BUY', entry, quantity, 20, '0.05')
            share = breakeven.distance() / entry * 100
            print(f'{quantity} shares bought at {entry}: sell at {breakeven.price()} or more, {share:.2f}% higher')
        for brokerage_per_order in (0, 20):
            sold = BreakevenPrice(self.option_rate, 'SELL', '177.00', 65, brokerage_per_order, '0.05')
            print(f'65 option units sold at 177.00 with {brokerage_per_order} brokerage an order: buy back at {sold.price()} or less, exactly {sold.exact_price()}')


if __name__ == '__main__':
    QuantityAndBrokerageExample().run()
