"""Prices one round trip in a NIFTY option at a broker that charges no brokerage and at one that charges 20 rupees an order.

`TradeCharges` takes the brokerage for every order behind the fills and adds GST to it, as a bill does. This program buys 65 units at 177.00 and sells them at 178.00, a profit of 65 rupees before charges, and prices it twice.

Notice that the 20-rupee broker turns the profit into a loss: the two orders cost 40 rupees plus 7.20 of GST.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/trade_charges/TradeCharges/example_2_one_trade_at_two_brokers.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)
from unified_broker_interface.utilities.execution_costs.trade_charges import (
    TradeCharges,
)


class OneTradeAtTwoBrokersExample:
    """Prices the same trade with and without brokerage.

    Attributes:
        charge_rate (ChargeRate): The NSE index option row.
    """

    def __init__(self):
        """Builds the option row.

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

    def run(self):
        """Prints each charge and the result at both brokers.

        Returns:
            None: This method returns nothing.
        """
        bought = decimal.Decimal('177.00') * 65
        sold = decimal.Decimal('178.00') * 65
        for broker, brokerage_per_order in (('No brokerage', 0), ('20 rupees an order', 20)):
            charges = TradeCharges(self.charge_rate, bought, sold, 2 * brokerage_per_order)
            print(broker)
            print(f'  STT {charges.stt():.2f}, exchange {charges.exchange_charge():.2f}, SEBI {charges.sebi_fee():.2f}, stamp {charges.stamp_duty():.2f}')
            print(f'  brokerage {charges.brokerage:.2f}, GST {charges.gst():.2f}, total {charges.total():.2f}')
            print(f'  result after charges: {charges.net_profit():.2f}')


if __name__ == '__main__':
    OneTradeAtTwoBrokersExample().run()
