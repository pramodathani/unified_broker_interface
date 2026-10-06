"""Shows a marketable peg with `reaches_size` setting its limit as deep into the offers as each order's size needs.

A marketable limit is normally two ticks past the best offer, so an order bigger than the first two levels fills only part at once and chases the rest. With `reaches_size`, `PegPricing.size_price` finds the deepest visible offer the order's unfilled quantity reaches, and `reaching` sends whichever of that and the usual price is further into the book. The book here offers 100 at each price from 1000.05 to 1000.25. Nothing is read from Redis or sent anywhere.

Notice that a buy of 10 keeps the usual 1000.15, a buy of 350 goes to 1000.20, a buy of 600 stops at the last visible level, 1000.25, and that with the setting off `size_price` gives nothing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_5_reaching_the_size_of_the_order.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.peg_pricing import (
    PegPricing,
)

QUANTITIES = [
    10,
    350,
    600,
]


class ReachingTheSizeExample:
    """Prices buys of three sizes with and without `reaches_size`.

    Attributes:
        view (MarketView): The book, with a tick of five paise.
    """

    def __init__(self):
        """Builds the book.

        Returns:
            None: This method returns nothing.
        """
        bids = []
        offers = []
        for index in range(5):
            bids.append({
                'price': round(1000.00 - index * 0.05, 2),
                'quantity': 100,
            })
            offers.append({
                'price': round(1000.05 + index * 0.05, 2),
                'quantity': 100,
            })
        quote = {
            'last_price': 1000.05,
            'depth': {
                'buy': bids,
                'sell': offers,
            },
        }
        self.view = MarketView(quote, decimal.Decimal('0.05'))

    def run(self):
        """Prints each size's prices.

        Returns:
            None: This method returns nothing.
        """
        peg = PegPricing('opposite_touch', -2, on_empty_book='refuse', reaches_size=True)
        usual = peg.wanted_price(self.view, 'BUY')
        print(f'Usual price, two ticks past the offer: {usual}')
        for quantity in QUANTITIES:
            size_price = peg.size_price(self.view, 'BUY', quantity)
            print(f'BUY {quantity}: the size reaches {size_price}, so the limit is {peg.reaching(usual, size_price, "BUY")}')
        sell_size_price = peg.size_price(self.view, 'SELL', 350)
        print(f'SELL 350: the size reaches {sell_size_price}, so the limit is {peg.reaching(peg.wanted_price(self.view, "SELL"), sell_size_price, "SELL")}')
        plain = PegPricing('opposite_touch', -2, on_empty_book='refuse')
        print(f'With the setting off, the size reaches: {plain.size_price(self.view, "BUY", 350)}')
        print(f'Described: {peg.described()}')


if __name__ == '__main__':
    ReachingTheSizeExample().run()
