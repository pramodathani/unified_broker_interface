"""Walks a chasing buy from the bid towards the offer, one tick every five seconds, until it reaches the offer.

`ChasePricing.priced_body` sends the order at its own touch. The first tick after it rests starts the clock in the pricing's memory, and `moved_prices` then steps it one tick each time the wait is up, from where it is rather than from the book, never past the other side's touch. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/chase_pricing/ChasePricing/example_1_steps_every_five_seconds.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.chase_pricing import (
    ChasePricing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
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


class StepsEveryFiveSecondsExample:
    """Walks a chasing buy through its steps."""

    def run(self):
        """Prints each tick.

        Returns:
            None: This method returns nothing.
        """
        pricing = ChasePricing(1, 5.0, None)
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        quotes = maker.book(1000.00, 1000.15)
        print(f'Reads quotes: {pricing.needs_prices()}, moves: {pricing.moves()}')
        body = pricing.priced_body(plan_order, {'quantity': 10}, 'BUY', quotes, {})
        print(f'Sent as: {body}')
        leg = maker.resting('BUY', float(body['price']))
        memory = {}
        for now in (0.0, 3.0, 5.0, 10.0, 15.0, 20.0):
            moved = pricing.moved_prices(plan_order, memory, leg, quotes, now)
            print(f'At {now} seconds: move {moved}')
            if moved is not None:
                leg.price = float(moved[0])
        print(f'Memory: {memory}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    StepsEveryFiveSecondsExample().run()
