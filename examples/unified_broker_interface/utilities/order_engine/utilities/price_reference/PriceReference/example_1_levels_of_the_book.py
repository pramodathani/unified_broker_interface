"""Works out an order price from the live quote for each kind of price reference, for a buy and for a sell.

A caller placing an order through `POST /api/orders/place` can send `price_reference` instead of a price, such as "the second best offer plus a tenth of a per cent". The order engine hands the parsed reference, the instrument's live quote and its tick size to `PriceReference.resolve`, which answers with a price on the tick. This program builds the quote by hand in the shape `unified:quotes:live` holds, with the prices as the JSON floats they arrive as, and uses a plain `OrderRequest` as the rounder, which is the object that owns tick rounding.

Nothing is read from Redis. Notice that the midpoint of 1000.05 and 1000.10 rounds down for a buy and up for a sell, so a resting order rests rather than crossing; that a `marketable` reference rounds the other way, towards filling; and that offsets always move the price towards filling, so a buy pays more and a sell asks less. The program also calls the helper methods on their own, to show the pieces `resolve` is built from.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_reference/PriceReference/example_1_levels_of_the_book.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.order_engine.utilities.price_reference import (
    PriceReference,
)


class LevelsOfTheBookExample:
    """Resolves several price references against one quote and prints the prices.

    Attributes:
        resolver (PriceReference): The resolver being shown.
        quote (dict): The instrument's live quote.
        tick_size (decimal.Decimal): The instrument's tick size.
        references (list): The parsed references to resolve.
    """

    def __init__(self):
        """Builds the resolver, the quote and the references.

        Returns:
            None: This method returns nothing.
        """
        self.resolver = PriceReference(OrderRequest())
        self.tick_size = decimal.Decimal('0.05')
        self.quote = {
            'last_price': 1000.0999999999999,
            'average_price': 999.83,
            'depth': {
                'buy': [
                    {
                        'price': 1000.0500000000001,
                        'quantity': 150,
                        'orders': 3,
                    },
                    {
                        'price': 1000.0,
                        'quantity': 420,
                        'orders': 6,
                    },
                ],
                'sell': [
                    {
                        'price': 1000.0999999999999,
                        'quantity': 90,
                        'orders': 2,
                    },
                    {
                        'price': 1000.15,
                        'quantity': 310,
                        'orders': 5,
                    },
                ],
            },
        }
        self.references = [
            {
                'kind': 'absolute',
                'price': decimal.Decimal('998.50'),
            },
            {
                'kind': 'last',
            },
            {
                'kind': 'vwap',
            },
            {
                'kind': 'mid',
            },
            {
                'kind': 'bid_level',
                'level': 2,
            },
            {
                'kind': 'offer_level',
                'level': 2,
                'buffer_percent': decimal.Decimal('0.1'),
            },
            {
                'kind': 'marketable',
                'offset_ticks': 2,
            },
        ]

    def run(self):
        """Prints each reference's price for both sides, then the helper methods' answers.

        Returns:
            None: This method returns nothing.
        """
        for reference in self.references:
            buy_price = self.resolver.resolve(reference, self.quote, 'BUY', self.tick_size)
            sell_price = self.resolver.resolve(reference, self.quote, 'SELL', self.tick_size)
            print(f'{reference}: BUY {buy_price}, SELL {sell_price}')
        print(f'passive_side for a mid buy: {self.resolver.passive_side("mid", "BUY")}')
        print(f'passive_side for a marketable buy: {self.resolver.passive_side("marketable", "BUY")}')
        mid = self.resolver.from_quote('mid', self.references[3], self.quote, 'BUY', self.tick_size)
        print(f'from_quote mid before rounding: {mid}')
        offer = self.resolver.level_price(self.quote, 'sell', 2, 'offer_level', self.tick_size)
        print(f'level_price of the second offer: {offer}')
        snapped = self.resolver.number(1000.0999999999999, 'last_price', 'last', self.tick_size)
        print(f'number of 1000.0999999999999: {snapped}')
        moved = self.resolver.with_offsets(offer, self.references[5], 'BUY', self.tick_size)
        print(f'with_offsets of {offer} plus 0.1% for a buy: {moved}')


if __name__ == '__main__':
    LevelsOfTheBookExample().run()
