"""Shows how a held sell order reads a single quote: the depth on each side, its own price level and whether the bid has reached it.

A `VirtualQueue` reads everything it knows from unified quotes. This program asks a sell of 200 at 1,512.50 the questions it asks of each quote, one by one: how it spells prices and quantities, which levels it can read from each side of the depth, how much rests at its price, what the best bid is, whether that bid has reached its price, and whether a trade happened beyond its price.

The quotes are plain dictionaries in the unified quote shape, including one malformed level that the reader skips. Notice that a price beyond the last level of a full five-level book cannot be seen and gives None, and that "better" and "traded through" point the other way for a sell than for a buy.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_queue/VirtualQueue/example_2_reading_one_quote.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)


class ReadingOneQuoteExample:
    """Asks one sell order's estimate every question it asks of a quote, and prints the answers.

    Attributes:
        estimate (VirtualQueue): A sell of 200 at 1,512.50.
        quote (dict): A quote with three offer levels, two bid levels and one unreadable level.
        full_quote (dict): A quote showing all five offer levels, all better than the order's price.
    """

    def __init__(self):
        """Builds the estimate and the two quotes.

        Returns:
            None: This method returns nothing.
        """
        self.estimate = VirtualQueue(
            'parent-7',
            'NSE:RELIANCE',
            'SELL',
            '1512.5',
            200,
        )
        self.quote = {
            'broker': 'dhan',
            'volume': 84000,
            'last_price': 1512.10,
            'received_at': 1759210000.0,
            'depth': {
                'buy': [
                    {
                        'price': 1512.10,
                        'quantity': 350,
                    },
                    {
                        'price': 1512.00,
                        'quantity': 900,
                    },
                ],
                'sell': [
                    {
                        'price': 1512.30,
                        'quantity': 120,
                    },
                    {
                        'price': '1512.50',
                        'quantity': 640,
                    },
                    {
                        'price': 'not a price',
                        'quantity': 10,
                    },
                    {
                        'price': 1512.80,
                        'quantity': 75,
                    },
                ],
            },
        }
        full_offers = []
        for step in range(5):
            full_offers.append(
                {
                    'price': 1511.00 + step * 0.10,
                    'quantity': 100,
                },
            )
        self.full_quote = {
            'broker': 'dhan',
            'volume': 84100,
            'last_price': 1512.60,
            'depth': {
                'buy': [
                    {
                        'price': 1510.90,
                        'quantity': 300,
                    },
                ],
                'sell': full_offers,
            },
        }

    def run(self):
        """Prints each reading of the quotes.

        Returns:
            None: This method returns nothing.
        """
        print(f'Limit price kept as: {self.estimate.price}')
        print(f'as_price(98): {self.estimate.as_price(98)}, as_price("98.0"): {self.estimate.as_price("98.0")}, as_price("NaN"): {self.estimate.as_price("NaN")}')
        print(f'as_quantity("640"): {self.estimate.as_quantity("640")}, as_quantity(True): {self.estimate.as_quantity(True)}')
        print(f'Offer levels read: {self.estimate.levels(self.quote, "sell")}')
        print(f'Bid levels read: {self.estimate.levels(self.quote, "buy")}')
        print(f'Resting at 1512.50 on the offer side: {self.estimate.visible_at_price(self.quote)}')
        print(f'Best bid, the opposite touch: {self.estimate.opposite_touch(self.quote)}')
        print(f'Bid has reached 1512.50: {self.estimate.is_touched(self.quote)}')
        lower = decimal.Decimal('1512.30')
        higher = decimal.Decimal('1512.80')
        print(f'For a sell, 1512.30 is better than 1512.80: {self.estimate.is_better(lower, higher)}')
        print(f'A trade at 1512.80 went through the price: {self.estimate.traded_through(higher)}')
        print(f'A trade at 1512.30 went through the price: {self.estimate.traded_through(lower)}')
        print(f'Resting at 1512.50 behind a full book ending at 1511.40: {self.estimate.visible_at_price(self.full_quote)}')
        self.quote['depth']['buy'][0]['price'] = 1512.50
        print(f'Bid raised to 1512.50, reached now: {self.estimate.is_touched(self.quote)}')


if __name__ == '__main__':
    ReadingOneQuoteExample().run()
