"""Reads everything the margin estimate needs from one NIFTY option leg.

A `PricedLeg` joins an order with the catalogue identity of its instrument, its last traded price and its underlying's last traded price, which the funds check's Lua script reads from Redis in one command. This program builds one with the NIFTY 22800 call and the prices of 2026-09-30 at about 10:40, so it needs nothing running.

Notice that the strike arrives as the text `22800.0` in the identity and comes out as a number, and that the market category is `derivatives`, which is the money pool the funds check looks in first.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/priced_leg/PricedLeg/example_1_reading_an_option_leg.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)


class StandInOrder:
    """An order carrying what a priced leg reads.

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
            price (decimal.Decimal | None): The limit price.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.product = product
        self.quantity = quantity
        self.price = price
        self.trigger_price = None


class ReadingAnOptionLegExample:
    """Prints what a sold NIFTY call leg carries.

    Attributes:
        leg (PricedLeg): The leg.
    """

    def __init__(self):
        """Builds the leg.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-06',
            'strike_price': '22800.0',
            'option_type': 'CE',
        }
        order = StandInOrder('SELL', 'NRML', 65, decimal.Decimal('122.5'))
        self.leg = PricedLeg(
            'nifty-2026-10-06-22800-ce',
            order,
            identity,
            decimal.Decimal('122.5'),
            decimal.Decimal('22721.25'),
        )

    def run(self):
        """Prints the leg's identity fields, side and prices.

        Returns:
            None: This method returns nothing.
        """
        print(f'Segment: {self.leg.segment()}')
        print(f'Shape: {self.leg.shape()}, option {self.leg.is_option()}, future {self.leg.is_future()}')
        print(f'Underlying: {self.leg.underlying_symbol()} expiring {self.leg.expiry_date()}')
        print(f'Strike: {self.leg.strike_price()} {self.leg.option_type()}')
        print(f'Buys: {self.leg.is_buy()}, direction {self.leg.direction()}, units {self.leg.units()}')
        print(f'Trade price: {self.leg.trade_price()}, underlying at {self.leg.underlying_price}')
        print(f'Market category: {self.leg.market_category()}')


if __name__ == '__main__':
    ReadingAnOptionLegExample().run()
