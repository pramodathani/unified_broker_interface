"""Shows a chasing buy waiting a full interval after a caller moves its price through PUT /api/orders/modify, then carrying on from the caller's price.

The chase steps one tick every five seconds from the bid at 1000.00 towards the offer at 1000.20. It steps to 1000.05 at five seconds, and at seven seconds the caller moves the order to 1000.10. Without `carry_on`, the step due at ten seconds would move the caller's price on three seconds after it was set. `ChasePricing.carry_on` restarts the wait by setting `stepped_at` to the moment of the change, so nothing moves at ten seconds, and the next step comes at twelve seconds, one tick on from the caller's price. A modify that leaves the price alone returns None.

A small stand-in plays the plan order with a tick of five paise. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/chase_pricing/ChasePricing/example_3_waits_after_the_callers_price.py
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


class WaitsAfterTheCallersPriceExample:
    """Walks a chasing buy through a caller's change.

    Attributes:
        pricing (ChasePricing): The chase.
        plan_order (StandInPlanOrder): The stand-in plan order.
        quotes (dict): The book every tick carries.
    """

    def __init__(self):
        """Builds the chase and the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.pricing = ChasePricing(1, 5.0, None)
        self.plan_order = StandInPlanOrder()
        self.quotes = QuoteMaker().book(1000.00, 1000.20)

    def tick(self, memory, leg, now):
        """Sends one tick through the chase, prints the answer and follows any move.

        Args:
            memory (dict): The pricing's memory.
            leg (OrderLeg): The resting order.
            now (float): The time of the tick, in seconds.

        Returns:
            None: This method returns nothing.
        """
        moved = self.pricing.moved_prices(self.plan_order, memory, leg, self.quotes, now)
        print(f'At {now} seconds: move {moved}')
        if moved is not None:
            leg.price = float(moved[0])

    def run(self):
        """Prints each tick and the change.

        Returns:
            None: This method returns nothing.
        """
        leg = QuoteMaker().resting('BUY', 1000.00)
        memory = {}
        self.tick(memory, leg, 0.0)
        self.tick(memory, leg, 5.0)
        before = {
            'price': leg.price,
        }
        leg.price = 1000.10
        print(f'At 7.0 seconds the caller moves the price from {before["price"]} to {leg.price}')
        untouched_memory = dict(memory)
        print(f'Without carry_on, at 10.0 seconds: {self.pricing.moved_prices(self.plan_order, untouched_memory, leg, self.quotes, 10.0)}')
        print(f'carry_on: {self.pricing.carry_on(self.plan_order, memory, leg, before, self.quotes, 7.0)}')
        print(f'Memory: {memory}')
        self.tick(memory, leg, 10.0)
        self.tick(memory, leg, 12.0)
        unchanged = {
            'price': leg.price,
        }
        print(f'A modify that leaves the price alone: {self.pricing.carry_on(self.plan_order, memory, leg, unchanged, self.quotes, 13.0)}')


if __name__ == '__main__':
    WaitsAfterTheCallersPriceExample().run()
