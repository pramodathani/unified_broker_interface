"""Reads the best bid, best offer, last price and midpoint out of one live quote, and the touch each side of an order joins or crosses.

A `MarketView` wraps the quote the engine reads from `unified:quotes:live` for one instrument, together with its tick size. This program builds one such quote by hand, in the shape the unified quote script writes, with the prices as the JSON floats they arrive as, so the offer of 1000.10 is really 1000.0999999999999.

Nothing is read from Redis; the quote is a plain dictionary. Notice that every price read out of the book comes back snapped to the 0.05 tick, that the midpoint of a one-tick spread is left between two ticks, and that a buy joins the bid but has to reach the offer to fill now, while a sell is the other way round. The program also moves a price two ticks towards and away from the market for each side, and rounds the midpoint towards the passive side for a buyer and a seller.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/market_view/MarketView/example_1_reading_the_touch.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


class ReadingTheTouchExample:
    """Reads prices out of one quote and prints them.

    Attributes:
        view (MarketView): The view being shown.
    """

    def __init__(self):
        """Builds the view over a quote with three levels each side.

        Returns:
            None: This method returns nothing.
        """
        quote = {
            'last_price': 1000.0999999999999,
            'stale': False,
            'depth': {
                'buy': [
                    {
                        'price': 1000.0500000000001,
                        'quantity': 120,
                        'orders': 3,
                    },
                    {
                        'price': 1000.0,
                        'quantity': 450,
                        'orders': 7,
                    },
                    {
                        'price': 999.95,
                        'quantity': 300,
                        'orders': 4,
                    },
                ],
                'sell': [
                    {
                        'price': 1000.0999999999999,
                        'quantity': 80,
                        'orders': 2,
                    },
                    {
                        'price': 1000.15,
                        'quantity': 260,
                        'orders': 5,
                    },
                    {
                        'price': 1000.2,
                        'quantity': 610,
                        'orders': 9,
                    },
                ],
            },
        }
        self.view = MarketView(quote, decimal.Decimal('0.05'))

    def run(self):
        """Prints what the view reads out of the quote.

        Returns:
            None: This method returns nothing.
        """
        print(f'Readable: {self.view.is_readable()}, stale: {self.view.is_stale()}')
        print(f'Raw offer 1000.0999999999999 read as: {self.view.number(1000.0999999999999)}')
        print(f'Last traded price: {self.view.last()}')
        print(f'Best bid: {self.view.best_bid()}')
        print(f'Best offer: {self.view.best_offer()}')
        print(f'Third level of the offers: {self.view.level("sell", 3)}')
        print(f'Fourth level of the offers: {self.view.level("sell", 4)}')
        midpoint = self.view.mid()
        print(f'Midpoint: {midpoint}')
        print(f'Midpoint rounded for a buyer: {self.view.rounded(midpoint, "BUY")}')
        print(f'Midpoint rounded for a seller: {self.view.rounded(midpoint, "SELL")}')
        print(f'Midpoint rounded to the nearest tick: {self.view.rounded(midpoint)}')
        for side in [
            'BUY',
            'SELL',
        ]:
            own = self.view.own_touch(side)
            opposite = self.view.opposite_touch(side)
            print(f'{side}: joins {own}, fills now at {opposite}')
            closer = self.view.moved(own, 2, side, True)
            further = self.view.moved(own, 2, side, False)
            print(f'{side}: two ticks towards the market {closer}, two ticks away {further}')


if __name__ == '__main__':
    ReadingTheTouchExample().run()
