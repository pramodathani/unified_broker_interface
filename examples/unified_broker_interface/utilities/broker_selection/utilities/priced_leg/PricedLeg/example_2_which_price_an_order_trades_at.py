"""Shows which price a leg is valued at for a limit order, a stop order and a market order.

`trade_price` takes the order's limit price when it has one, else its trigger price, else the instrument's last traded price from Redis. A market order on an instrument with no quote has no price at all, and the funds check then skips the check rather than guess. This program builds four INFY legs, with prices from 2026-09-30, and also shows `decimal_or_none` reading the texts the Lua script returns.

Notice that the last case gives None, and that an empty text, `NaN` and `Infinity` are all read as no number.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/priced_leg/PricedLeg/example_2_which_price_an_order_trades_at.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)

INFY_IDENTITY = {
    'segment': 'nse_equities',
    'shape': 'security',
    'underlying_symbol': None,
    'expiry_date': None,
    'strike_price': None,
    'option_type': None,
}


class StandInOrder:
    """An order carrying what a priced leg reads.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): The product.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price.
        trigger_price (decimal.Decimal | None): The trigger price.
    """

    def __init__(self, price, trigger_price):
        """Builds a delivery buy of 10 shares.

        Args:
            price (decimal.Decimal | None): The limit price.
            trigger_price (decimal.Decimal | None): The trigger price.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = 'BUY'
        self.product = 'CNC'
        self.quantity = 10
        self.price = price
        self.trigger_price = trigger_price


class WhichPriceAnOrderTradesAtExample:
    """Prints the trade price of four legs and reads four texts.

    Attributes:
        cases (list): `(description, PricedLeg)` tuples.
    """

    def __init__(self):
        """Builds the four legs.

        Returns:
            None: This method returns nothing.
        """
        last_price = decimal.Decimal('1017.7')
        self.cases = [
            ('limit at 1015', PricedLeg('infy', StandInOrder(decimal.Decimal('1015'), None), INFY_IDENTITY, last_price, None)),
            ('stop-market triggered at 1020', PricedLeg('infy', StandInOrder(None, decimal.Decimal('1020')), INFY_IDENTITY, last_price, None)),
            ('market, quote held', PricedLeg('infy', StandInOrder(None, None), INFY_IDENTITY, last_price, None)),
            ('market, no quote', PricedLeg('infy', StandInOrder(None, None), INFY_IDENTITY, None, None)),
        ]

    def run(self):
        """Prints each leg's trade price, then reads some texts as numbers.

        Returns:
            None: This method returns nothing.
        """
        for description, leg in self.cases:
            print(f'{description}: trade price {leg.trade_price()}, market {leg.market_category()}')
        texts = [
            '22683.4',
            '',
            'NaN',
            'Infinity',
        ]
        for text in texts:
            print(f'{text!r} reads as {PricedLeg.decimal_or_none(text)}')


if __name__ == '__main__':
    WhichPriceAnOrderTradesAtExample().run()
