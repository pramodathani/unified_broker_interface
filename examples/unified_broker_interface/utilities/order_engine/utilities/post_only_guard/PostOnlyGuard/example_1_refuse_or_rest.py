"""Checks a buy at 1000.10 against a book of 1000.00 bid and 1000.05 offered, which it would cross, once refusing and once resting.

`PostOnlyGuard.checked_body` answers the body and a refusal: with `refuse`, the refusal says why nothing was sent; with `rest`, the price is moved back to the bid and there is no refusal. A buy at the bid passes untouched. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/post_only_guard/PostOnlyGuard/example_1_refuse_or_rest.py
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


class RefuseOrRestExample:
    """Prints the guard's answers for crossing and resting prices."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        view = plan_order.view(QuoteMaker().book(1000.00, 1000.05))
        refusing = PostOnlyGuard('refuse')
        resting = PostOnlyGuard('rest')
        print(f'Refuse: {refusing.checked_body(view, {"order_type": "LIMIT", "price": "1000.10"}, "BUY")}')
        print(f'Rest: {resting.checked_body(view, {"order_type": "LIMIT", "price": "1000.10"}, "BUY")}')
        print(f'At the bid: {refusing.checked_body(view, {"order_type": "LIMIT", "price": "1000.00"}, "BUY")}')
        print(f'As a dry run shows them: {refusing.described()} and {resting.described()}')


if __name__ == '__main__':
    RefuseOrRestExample().run()
