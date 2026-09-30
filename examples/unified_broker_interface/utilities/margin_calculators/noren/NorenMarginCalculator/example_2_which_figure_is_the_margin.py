"""Reads Shoonya's real answers of 2026-09-30 and shows why `ordermargin`, not `marginused`, is the order's margin.

A Noren single-order answer carries `cash`, `marginused` and `ordermargin`. When the account can afford the order, `marginused` and `ordermargin` are the same; when it cannot, `remarks` says "Insufficient Balance" and `marginused` becomes the shortfall, the margin less the cash. `NorenMarginCalculator` therefore reads `ordermargin`. A basket answer's `marginusedtrade` is the margin once every leg has traded. This program also prints the account fields every Noren request starts with and one leg's fields, from `account_fields` and `noren_order`.

Notice that for the NIFTY future `marginused` is 171,296.19 while the margin is 176,246.49: the account's 4,950.30 of cash was taken off.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/noren/NorenMarginCalculator/example_2_which_figure_is_the_margin.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.shoonya import ShoonyaOrders
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.noren import (
    NorenMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)


class ShoonyaLikeCalculator(NorenMarginCalculator):
    """A Noren calculator for Shoonya, as `shoonya.py` defines it."""

    BROKER_NAME = 'shoonya'
    ORDER_CLASS = ShoonyaOrders


class WhichFigureIsTheMarginExample:
    """Reads two recorded answers and shows the request fields.

    Attributes:
        calculator (ShoonyaLikeCalculator): The calculator, with stand-in credentials.
    """

    def __init__(self):
        """Builds the calculator.

        Returns:
            None: This method returns nothing.
        """
        login = {
            'access_token': 'stand-in-token',
        }
        settings = {
            'ucc_code': 'STANDIN1',
        }
        self.calculator = ShoonyaLikeCalculator(login, settings)

    def run(self):
        """Prints the account fields, one order's fields, and the figures read from the answers.

        Returns:
            None: This method returns nothing.
        """
        print(f'Account fields: {self.calculator.account_fields()}')
        identity = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
        }
        handles = {
            'shoonya': {
                'broker_token': '48704',
                'order_symbol': 'NIFTY27OCT26F',
                'lot_size': '65.0',
                'tick_size': '0.1',
            },
        }
        future = Instrument('28312010-2d68-5c8d-8b42-a66bc13a7816', identity, handles)
        leg = ReferenceLeg('NIFTY future sold', future, 'SELL', 'NRML', 65, decimal.Decimal('22833.7'))
        print(f'Order fields: {self.calculator.noren_order(leg)}')
        order_answer = {
            'stat': 'Ok',
            'cash': '4950.30',
            'marginused': '171296.19',
            'remarks': 'Insufficient Balance',
            'marginusedprev': '0.00',
            'ordermargin': '176246.49',
        }
        basket_answer = {
            'stat': 'Ok',
            'marginused': '196915.48',
            'marginusedtrade': '75406.56',
            'marginusedprev': '0.00',
            'remarks': '',
        }
        print(f'marginused: {order_answer["marginused"]}, but the margin read is {self.calculator.read_order_margin(order_answer)}')
        print(f'Iron condor once every leg has traded: {self.calculator.read_basket_margin(basket_answer)}')


if __name__ == '__main__':
    WhichFigureIsTheMarginExample().run()
