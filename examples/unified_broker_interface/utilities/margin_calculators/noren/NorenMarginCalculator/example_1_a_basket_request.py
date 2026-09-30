"""Builds the Noren basket request for a NIFTY iron condor, with the first leg at the top level and the rest in `basketlists`.

`NorenMarginCalculator` holds everything Flattrade and Shoonya share, since both run the Noren platform: the `jData` and `jKey` form encoding, the account fields, and the two endpoints. Each broker's own module only names the broker and its order class. This program builds a basket request through Flattrade's order class with stand-in credentials and the real option symbols of 2026-09-30, and prints the fields, so the unusual layout can be seen.

It also builds the single-order request for the first leg, and shows `noren_request`, the helper both use to encode fields.

Notice that the bought 23200 call, the first leg, sits beside `uid` and `actid`, and the other three legs are in `basketlists` without them.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/noren/NorenMarginCalculator/example_1_a_basket_request.py
"""

import decimal
import json
import urllib.parse

from unified_broker_interface.utilities.broker_orders.flattrade import FlattradeOrders
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.noren import (
    NorenMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)


class FlattradeLikeCalculator(NorenMarginCalculator):
    """A Noren calculator for Flattrade, as `flattrade.py` defines it."""

    BROKER_NAME = 'flattrade'
    ORDER_CLASS = FlattradeOrders


class ABasketRequestExample:
    """Builds and prints the condor's basket request.

    Attributes:
        calculator (FlattradeLikeCalculator): The calculator, with stand-in credentials.
        legs (list): The four `ReferenceLeg` legs, bought ones first.
    """

    def __init__(self):
        """Builds the calculator and the legs.

        Returns:
            None: This method returns nothing.
        """
        login = {
            'access_token': 'stand-in-token',
        }
        settings = {
            'username': 'STANDIN1',
        }
        self.calculator = FlattradeLikeCalculator(login, settings)
        self.legs = [
            self.leg('NIFTY06OCT26C23200', 'BUY', '19.0'),
            self.leg('NIFTY06OCT26P22400', 'BUY', '38.1'),
            self.leg('NIFTY06OCT26C23000', 'SELL', '51.6'),
            self.leg('NIFTY06OCT26P22600', 'SELL', '82.0'),
        ]

    @staticmethod
    def leg(order_symbol, transaction_type, price_text):
        """One NIFTY option leg of one lot.

        Args:
            order_symbol (str): Flattrade's trading symbol.
            transaction_type (str): `BUY` or `SELL`.
            price_text (str): The price.

        Returns:
            ReferenceLeg: The leg.
        """
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
        }
        handles = {
            'flattrade': {
                'broker_token': '0',
                'order_symbol': order_symbol,
                'lot_size': '65.0',
                'tick_size': None,
            },
        }
        instrument = Instrument(order_symbol, identity, handles)
        return ReferenceLeg(order_symbol, instrument, transaction_type, 'NRML', 65, decimal.Decimal(price_text))

    def run(self):
        """Prints the endpoint and the decoded `jData` fields.

        Returns:
            None: This method returns nothing.
        """
        request = self.calculator.build_basket_request(self.legs)
        print(f'{request.method} {request.url}')
        form = urllib.parse.parse_qs(request.data)
        fields = json.loads(form['jData'][0])
        print(json.dumps(fields, indent=2))
        print(f'jKey: {form["jKey"][0]}')
        single = self.calculator.build_order_request(self.legs[0])
        print(f'One order alone goes to {single.url}')
        bare = self.calculator.noren_request('GetOrderMargin', {'uid': 'STANDIN1'})
        print(f'noren_request encodes its fields as {bare.data}')


if __name__ == '__main__':
    ABasketRequestExample().run()
