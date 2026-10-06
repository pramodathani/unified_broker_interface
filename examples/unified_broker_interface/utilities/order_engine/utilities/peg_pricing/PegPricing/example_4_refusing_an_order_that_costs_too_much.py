"""Shows a marketable peg with a maximum cost refusing orders that would cost too much to cross the spread.

With `maximum_cost_bps` set, `PegPricing.cost_refusal` works out, from the visible book, what crossing the spread would cost the whole order, as basis points of the mid-price, and gives a reason to refuse it when that is above the maximum, or when the visible book does not hold the whole order. The order engine asks it just before the order is sent, and a refusal is answered with HTTP 409. Here the book is 1000.00 bid and 1000.05 offered, with 100 at each of five levels, so a buy of 10 costs about 0.25 basis points, and a buy of 260 walks three levels. Nothing is read from Redis or sent anywhere.

Notice that the buy of 260 costs 0.67 basis points, allowed under a maximum of 1 and refused under 0.5, and that the buy of 600 is refused because the five levels hold only 500.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_4_refusing_an_order_that_costs_too_much.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.peg_pricing import (
    PegPricing,
)

CASES = [
    (
        1,
        10,
    ),
    (
        0.2,
        10,
    ),
    (
        1,
        260,
    ),
    (
        0.5,
        260,
    ),
    (
        100,
        600,
    ),
]


class RefusingAnOrderThatCostsTooMuchExample:
    """Asks a guarded peg about orders of three sizes under several maximums.

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
        """Prints each case's answer, and the setting as a dry run shows it.

        Returns:
            None: This method returns nothing.
        """
        for maximum, quantity in CASES:
            peg = PegPricing('opposite_touch', -2, on_empty_book='refuse', maximum_cost_bps=maximum)
            print(f'BUY {quantity} under a maximum of {maximum} bps: {peg.cost_refusal(self.view, "BUY", quantity)}')
        unguarded = PegPricing('opposite_touch', -2, on_empty_book='refuse')
        print(f'BUY 600 with no maximum: {unguarded.cost_refusal(self.view, "BUY", 600)}')
        print(f"Described: {PegPricing('opposite_touch', -2, on_empty_book='refuse', maximum_cost_bps=1).described()}")


if __name__ == '__main__':
    RefusingAnOrderThatCostsTooMuchExample().run()
