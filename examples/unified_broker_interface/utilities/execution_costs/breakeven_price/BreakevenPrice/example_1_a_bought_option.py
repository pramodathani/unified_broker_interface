"""Works out the real breakeven of a NIFTY option bought at 177.00, and checks that selling there loses nothing.

A `BreakevenPrice` is the exit price at which a position makes exactly nothing after every tax, fee and brokerage. `exact_price` is the unrounded answer and `price` rounds it to the tick on the safe side, up for a bought position.

Notice that the breakeven is 0.45 above the entry, not the entry itself, and that selling one tick below it loses money.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_price/BreakevenPrice/example_1_a_bought_option.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)
from unified_broker_interface.utilities.execution_costs.trade_charges import (
    TradeCharges,
)


class BoughtOptionExample:
    """Prints the breakeven and the result of selling at it and one tick under it.

    Attributes:
        charge_rate (ChargeRate): The NSE index option row.
        breakeven (BreakevenPrice): 65 units bought at 177.00, with no brokerage and a tick of 0.05.
    """

    def __init__(self):
        """Builds the row and the breakeven.

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
        )
        self.breakeven = BreakevenPrice(self.charge_rate, 'BUY', '177.00', 65, tick_size='0.05')

    def run(self):
        """Prints the breakeven and two exits.

        Returns:
            None: This method returns nothing.
        """
        print(f'Exact breakeven: {self.breakeven.exact_price()}')
        print(f'Rounded to the tick: {self.breakeven.price()}')
        print(f'Above the entry by: {self.breakeven.distance()}')
        print(f'Brokerage with GST: {self.breakeven.brokerage_with_gst()}')
        bought = decimal.Decimal('177.00') * 65
        for exit_price in (self.breakeven.price(), self.breakeven.price() - decimal.Decimal('0.05')):
            charges = TradeCharges(self.charge_rate, bought, exit_price * 65)
            print(f'Selling at {exit_price}: {charges.net_profit():.2f} after charges')


if __name__ == '__main__':
    BoughtOptionExample().run()
