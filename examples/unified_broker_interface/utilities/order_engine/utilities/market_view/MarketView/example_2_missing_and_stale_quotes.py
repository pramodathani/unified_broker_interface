"""Shows what a `MarketView` answers when the quote is missing, stale, one-sided or damaged.

An order type that watches the market asks its `MarketView` for a price on every tick, and when the price is not there it does nothing and looks again a second later. So every reader returns None instead of raising. This program builds four views: one with no quote at all, one whose tick size is unknown, one marked stale because its broker went silent, and one whose book has bids but no offers and whose last price is zero.

Each quote is a plain dictionary, so nothing is read from Redis. Notice that a stale quote is still readable, and it is the order type's job to check `is_stale` before acting; that a zero or unparseable price reads as None; and that the midpoint needs both sides of the book.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/market_view/MarketView/example_2_missing_and_stale_quotes.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


class MissingAndStaleQuotesExample:
    """Builds views over incomplete quotes and prints what each one can and cannot answer.

    Attributes:
        tick_size (decimal.Decimal): The instruments' tick size.
        views (list): Pairs of (description, MarketView).
    """

    def __init__(self):
        """Builds the four views.

        Returns:
            None: This method returns nothing.
        """
        self.tick_size = decimal.Decimal('0.05')
        good_quote = {
            'last_price': 250.35,
            'depth': {
                'buy': [
                    {
                        'price': 250.3,
                        'quantity': 900,
                        'orders': 6,
                    },
                ],
                'sell': [
                    {
                        'price': 250.4,
                        'quantity': 700,
                        'orders': 4,
                    },
                ],
            },
        }
        stale_quote = dict(good_quote)
        stale_quote['stale'] = True
        one_sided_quote = {
            'last_price': 0,
            'depth': {
                'buy': [
                    {
                        'price': 88.15,
                        'quantity': 50,
                        'orders': 1,
                    },
                ],
                'sell': [],
            },
        }
        self.views = [
            (
                'no quote',
                MarketView(None, self.tick_size),
            ),
            (
                'tick size unknown',
                MarketView(good_quote, None),
            ),
            (
                'stale quote',
                MarketView(stale_quote, self.tick_size),
            ),
            (
                'bids only, last price zero',
                MarketView(one_sided_quote, self.tick_size),
            ),
        ]

    def run(self):
        """Prints each view's answers.

        Returns:
            None: This method returns nothing.
        """
        for description, view in self.views:
            print(f'{description}:')
            print(f'  readable {view.is_readable()}, stale {view.is_stale()}')
            print(f'  last {view.last()}, bid {view.best_bid()}, offer {view.best_offer()}, mid {view.mid()}')
            print(f'  a buy joins {view.own_touch("BUY")} and fills at {view.opposite_touch("BUY")}')
            print(f'  250.33 rounded: {view.rounded(decimal.Decimal("250.33"))}')
            print(f'  250.35 moved one tick towards the market for a sell: {view.moved(decimal.Decimal("250.35"), 1, "SELL", True)}')
        checker = self.views[2][1]
        print(f'Unparseable price: {checker.number("not a price")}')
        print(f'Negative price: {checker.number(-4.5)}')


if __name__ == '__main__':
    MissingAndStaleQuotesExample().run()
