"""Estimates the margin of seven single orders and sets each beside what the brokers' calculators answered.

A `MarginEstimate` works out the exchange's margin from the margin rate table and the prices Redis holds, without calling a broker. This program prices the orders sent to every broker's margin calculator on 2026-09-30 at about 10:40 IST, at the same prices, with the rates the DDL seeds; the broker column is Zerodha's answer, which Dhan, Fyers, Groww and Kotak matched to within half a percent.

Notice that every estimate lands within 1% of the brokers except the sold call, which is about 3% higher, because the estimate charges it what a future on the whole index would need. A delivery sell needs no cash, since the broker checks holdings instead.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_estimate/MarginEstimate/example_1_single_orders_against_the_brokers.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_selection.utilities.margin_estimate import (
    MarginEstimate,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)

NIFTY_SPOT = decimal.Decimal('22721.25')


class StandInOrder:
    """An order carrying what the estimate reads.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): The product.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price.
        trigger_price (decimal.Decimal | None): The trigger price.
    """

    def __init__(self, transaction_type, product, quantity, price):
        """Builds the order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            quantity (int): The quantity in units.
            price (decimal.Decimal): The limit price.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.product = product
        self.quantity = quantity
        self.price = price
        self.trigger_price = None


class SingleOrdersAgainstTheBrokersExample:
    """Prints each estimate beside the broker's answer.

    Attributes:
        estimate (MarginEstimate): The estimate.
        cases (list): `(description, PricedLeg, broker answer)` tuples.
    """

    def __init__(self):
        """Builds the rates and the six orders.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            MarginRate('nse_equities', '', decimal.Decimal('0.20'), decimal.Decimal('0')),
            MarginRate('nse_equity_index_futures', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
            MarginRate('nse_equity_index_options', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
            MarginRate('mcx_commodity_futures', 'CRUDEOIL', decimal.Decimal('0.302'), decimal.Decimal('0.0125')),
        ]
        self.estimate = MarginEstimate(MarginRateTable(logging.getLogger('example'), rows))
        equity = self.identity('nse_equities', 'security', None, None, None)
        future = self.identity('nse_equity_index_futures', 'future', 'NIFTY', None, None)
        call = self.identity('nse_equity_index_options', 'option', 'NIFTY', '22800', 'CE')
        crude = self.identity('mcx_commodity_futures', 'future', 'CRUDEOIL', None, None)
        self.cases = [
            ('INFY delivery buy, 1 share', self.leg(equity, 'BUY', 'CNC', 1, '1017.7'), '1017.40'),
            ('INFY delivery sell, 1 share', self.leg(equity, 'SELL', 'CNC', 1, '1017.7'), 'holdings'),
            ('INFY intraday buy, 1 share', self.leg(equity, 'BUY', 'MIS', 1, '1017.7'), '203.48'),
            ('NIFTY future sold, 1 lot', self.leg(future, 'SELL', 'NRML', 65, '22833.7'), '167109.41'),
            ('NIFTY 22800 call sold, 1 lot', self.leg(call, 'SELL', 'NRML', 65, '122.5'), '161608.53'),
            ('NIFTY 22800 call bought, 1 lot', self.leg(call, 'BUY', 'NRML', 65, '122.5'), '7962.50'),
            ('Crude oil future bought, 1 lot', self.leg(crude, 'BUY', 'NRML', 100, '8618'), '271072.50'),
        ]

    @staticmethod
    def identity(segment, shape, underlying_symbol, strike_price, option_type):
        """A catalogue identity.

        Args:
            segment (str): The segment.
            shape (str): `security`, `future` or `option`.
            underlying_symbol (str | None): The underlying.
            strike_price (str | None): The strike.
            option_type (str | None): `CE`, `PE` or None.

        Returns:
            dict: The identity.
        """
        return {
            'segment': segment,
            'shape': shape,
            'underlying_symbol': underlying_symbol,
            'expiry_date': '2026-10-27',
            'strike_price': strike_price,
            'option_type': option_type,
        }

    @staticmethod
    def leg(identity, transaction_type, product, quantity, price_text):
        """One priced leg, with NIFTY's spot level as the underlying's price.

        Args:
            identity (dict): The identity.
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            quantity (int): The quantity in units.
            price_text (str): The limit price.

        Returns:
            PricedLeg: The leg.
        """
        price = decimal.Decimal(price_text)
        order = StandInOrder(transaction_type, product, quantity, price)
        underlying_price = None
        if identity['underlying_symbol'] == 'NIFTY':
            underlying_price = NIFTY_SPOT
        return PricedLeg('leg', order, identity, price, underlying_price)

    def run(self):
        """Prints each order's category, estimate and the broker's answer.

        Returns:
            None: This method returns nothing.
        """
        for description, leg, broker_answer in self.cases:
            margin = self.estimate.leg_margin(leg)
            category = self.estimate.margin_category(leg)
            print(f'{description} [{category}]: estimate {margin:,.2f}, broker {broker_answer}')


if __name__ == '__main__':
    SingleOrdersAgainstTheBrokersExample().run()
