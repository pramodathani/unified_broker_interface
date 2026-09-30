"""Builds one reference leg and reads each broker's handle for it.

A `ReferenceLeg` describes an order once, in terms every broker's calculator can translate: the instrument with all of its order handles, the side, the product, the quantity in units and the price. Each calculator picks out its own handle with `handle`. This program builds the NIFTY October future sold at 22,833.70 with three brokers' real handles of 2026-09-30.

Notice that the three brokers name the same future three ways, and that a broker without a handle gets None, which makes its calculator's `takes` say no.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/reference_leg/ReferenceLeg/example_1_one_leg_for_every_broker.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)


class OneLegForEveryBrokerExample:
    """Builds the leg and prints each broker's handle.

    Attributes:
        leg (ReferenceLeg): The leg.
    """

    def __init__(self):
        """Builds the leg.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
        }
        handles = {
            'zerodha': {
                'broker_token': '12468226',
                'order_symbol': 'NIFTY26OCTFUT',
            },
            'fyers': {
                'broker_token': '101126102748704',
                'order_symbol': 'NSE:NIFTY26OCTFUT',
            },
            'shoonya': {
                'broker_token': '48704',
                'order_symbol': 'NIFTY27OCT26F',
            },
        }
        future = Instrument('28312010-2d68-5c8d-8b42-a66bc13a7816', identity, handles)
        self.leg = ReferenceLeg('NIFTY future sold', future, 'SELL', 'NRML', 65, decimal.Decimal('22833.7'))

    def run(self):
        """Prints the leg and each broker's order symbol.

        Returns:
            None: This method returns nothing.
        """
        print(f'{self.leg.name}: {self.leg.transaction_type} {self.leg.units} units {self.leg.product} at {self.leg.price}, buys {self.leg.is_buy()}')
        for broker_name in ['zerodha', 'fyers', 'shoonya', 'stoxkart']:
            handle = self.leg.handle(broker_name)
            if handle is None:
                print(f'{broker_name}: no handle')
            else:
                print(f'{broker_name}: {handle["order_symbol"]}')


if __name__ == '__main__':
    OneLegForEveryBrokerExample().run()
