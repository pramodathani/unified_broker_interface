"""Prices a buy pegged to its own side of the book and follows the bid as it moves.

`PegPricing.priced_body` sends a limit at the reference now, and on every later tick `moved_prices` says where the resting order should be. A positive `offset_ticks` sits further from filling. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_1_follows_the_bid.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
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


class FollowsTheBidExample:
    """Prices a pegged buy and follows the bid."""

    def run(self):
        """Prints each price.

        Returns:
            None: This method returns nothing.
        """
        pricing = PegPricing('own_touch', 1)
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        print(f'Reads quotes: {pricing.needs_prices()}, moves: {pricing.moves()}')
        body = pricing.priced_body(plan_order, {'quantity': 10}, 'BUY', maker.book(1000.00, 1000.05), {})
        print(f'Sent as: {body}')
        leg = maker.resting('BUY', 999.95)
        for bid, offer in ((1000.20, 1000.25), (999.80, 999.85)):
            print(f'Bid {bid}: move to {pricing.moved_prices(plan_order, {}, leg, maker.book(bid, offer), 0.0)}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    FollowsTheBidExample().run()
