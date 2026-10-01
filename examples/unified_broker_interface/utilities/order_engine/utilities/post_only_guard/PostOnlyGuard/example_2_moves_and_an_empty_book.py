"""Shows the guard on a resting sell that is about to move, and on a book that cannot be read yet.

`PostOnlyGuard.would_cross` says whether a price would trade. `checked_move` skips a move that would cross with `refuse`, and holds it at the offer with `rest`. With no book, `checked_body` answers no body, so the order waits for a tick that carries one. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/post_only_guard/PostOnlyGuard/example_2_moves_and_an_empty_book.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.post_only_guard import (
    PostOnlyGuard,
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
    """Builds quotes with a chosen touch."""

    def book(self, bid, offer):
        """The quotes a tick carries, with one level on each side.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INSTRUMENT_ID: {
                'last_price': offer,
                'depth': {
                    'buy': [
                        {
                            'price': bid,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': offer,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }

    def resting(self, side, price):
        """A resting broker order on a side at a price.

        Args:
            side (str): BUY or SELL.
            price (float): Its limit.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.price = price
        leg.quantity = 10
        leg.state = 'acknowledged'
        return leg


class MovesAndAnEmptyBookExample:
    """Prints the guard's answers for a moving sell and an empty book."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        view = plan_order.view(QuoteMaker().book(1000.00, 1000.05))
        refusing = PostOnlyGuard('refuse')
        resting = PostOnlyGuard('rest')
        price = decimal.Decimal('1000.00')
        print(f'A sell at 1000.00 would cross: {refusing.would_cross(price, "SELL", view)}')
        print(f'Moving it there, refuse: {refusing.checked_move(view, price, "SELL")}, rest: {resting.checked_move(view, price, "SELL")}')
        print(f'A move to 1000.10: {refusing.checked_move(view, decimal.Decimal("1000.10"), "SELL")}')
        print(f'With no book: {refusing.checked_body(plan_order.view({}), {"order_type": "LIMIT", "price": "1000.10"}, "SELL")}')


if __name__ == '__main__':
    MovesAndAnEmptyBookExample().run()
