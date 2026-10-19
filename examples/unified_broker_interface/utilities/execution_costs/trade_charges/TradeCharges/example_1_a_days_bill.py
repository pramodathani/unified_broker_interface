"""Works out the charges on a day of NIFTY option trades and sets them beside Flattrade's bill for the same fills.

A `TradeCharges` takes the rupees bought and sold in one segment and works out every charge as a bill does. This program uses the 178 round trips of 19 October 2026, worth 20,49,940.75 bought and 20,48,683.00 sold at Flattrade, which charges no brokerage.

Notice that the exchange charge, the SEBI fee and the GST match the bill to the paisa, and STT and stamp duty differ only because the bill rounds them to the rupee.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/trade_charges/TradeCharges/example_1_a_days_bill.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)
from unified_broker_interface.utilities.execution_costs.trade_charges import (
    TradeCharges,
)

BILL = {
    'brokerage': '0.00',
    'stt': '3073.00',
    'exchange_charge': '1456.24',
    'sebi_fee': '4.10',
    'stamp_duty': '61.00',
    'gst': '262.86',
    'total': '4857.20',
}


class DaysBillExample:
    """Prints the worked-out charges beside the bill's.

    Attributes:
        charges (TradeCharges): The day's charges.
    """

    def __init__(self):
        """Builds the day's charges.

        Returns:
            None: This method returns nothing.
        """
        charge_rate = ChargeRate(
            'nse_equity_index_options',
            'fno',
            decimal.Decimal('0'),
            decimal.Decimal('0.0015'),
            decimal.Decimal('0.0003553'),
            decimal.Decimal('0.000001'),
            decimal.Decimal('0.00003'),
            decimal.Decimal('0.18'),
        )
        self.charges = TradeCharges(
            charge_rate,
            decimal.Decimal('2049940.75'),
            decimal.Decimal('2048683.00'),
        )

    def run(self):
        """Prints each charge, the bill's figure and the turnover, then the day's result.

        Returns:
            None: This method returns nothing.
        """
        print(f'Turnover: {self.charges.turnover():,.2f}')
        for name, worked_out in self.charges.parts().items():
            print(f'{name}: {worked_out:,.2f}, bill {BILL[name]}')
        trading = self.charges.sell_value - self.charges.buy_value
        print(f'Trading result: {trading:,.2f}')
        print(f'After charges: {self.charges.net_profit():,.2f}, bill -6,114.95')


if __name__ == '__main__':
    DaysBillExample().run()
