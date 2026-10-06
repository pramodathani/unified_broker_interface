"""Shows a peg to the opposite touch that refuses, rather than waits, when the book cannot price it.

This is how a market order sent as a marketable limit is priced: two ticks through the other side's best price, so it fills against what is resting there. With `on_empty_book` set to `refuse`, `PegPricing.empty_book_refusal` gives the reason the order is refused when `priced_body` could make no price: no one on the other side, no quote at all, or a quote marked stale. A peg left at the default `wait` gives no reason, and the order waits for a tick that can price it. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_3_refusing_an_empty_book.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.peg_pricing import (
    PegPricing,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInPlanOrder:
    """Stands in for the plan order, which reads a quote into a market view."""

    def view(self, quotes):
        """The market, as the instrument's quote shows it, with a tick of five paise.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(INSTRUMENT_ID), decimal.Decimal('0.05'))


class QuoteMaker:
    """Builds quotes with one level on each side that has one."""

    def book(self, bids, offers, stale=False):
        """The quotes a tick carries.

        Args:
            bids (list): The bid prices, best first, as floats.
            offers (list): The offer prices, best first, as floats.
            stale (bool): Whether the quote is marked stale.

        Returns:
            dict: The quotes, by instrument id.
        """
        buy_levels = []
        for price in bids:
            buy_levels.append({
                'price': price,
                'quantity': 100,
            })
        sell_levels = []
        for price in offers:
            sell_levels.append({
                'price': price,
                'quantity': 100,
            })
        quote = {
            'last_price': 1000.05,
            'depth': {
                'buy': buy_levels,
                'sell': sell_levels,
            },
        }
        if stale:
            quote['stale'] = True
        return {
            INSTRUMENT_ID: quote,
        }


class RefusingAnEmptyBookExample:
    """Prints the price of a marketable peg on a full book and the refusals on books that cannot price it."""

    def run(self):
        """Prints each price and refusal.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        marketable = PegPricing('opposite_touch', -2, True, False, 'refuse')
        waiting = PegPricing('opposite_touch', -2)
        full = maker.book([1000.00], [1000.05])
        print(f'Buy on a full book: {marketable.priced_body(plan_order, {"order_type": "MARKET"}, "BUY", full, {})}')
        print(f'Sell on a full book: {marketable.priced_body(plan_order, {"order_type": "MARKET"}, "SELL", full, {})}')
        books = [
            ('no offers', maker.book([1000.00], []), 'BUY'),
            ('no bids', maker.book([], [1000.05]), 'SELL'),
            ('no quote', {}, 'BUY'),
            ('a stale quote', maker.book([1000.00], [1000.05], True), 'BUY'),
        ]
        for name, quotes, side in books:
            view = plan_order.view(quotes)
            priced = marketable.priced_body(plan_order, {'order_type': 'MARKET'}, side, quotes, {})
            print(f'{side} with {name}: priced {priced}, refused because {marketable.empty_book_refusal(view, side)}')
        no_offers = plan_order.view(maker.book([1000.00], []))
        print(f'A peg that waits gives no refusal: {waiting.empty_book_refusal(no_offers, "BUY")}')
        print(f'As a dry run shows it: {marketable.described()}')


if __name__ == '__main__':
    RefusingAnEmptyBookExample().run()
