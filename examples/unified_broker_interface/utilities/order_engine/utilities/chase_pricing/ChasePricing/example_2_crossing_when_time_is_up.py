"""Shows a chasing sell that crosses the spread once its time is up, and how far a step may go.

With `cross_after_seconds`, `ChasePricing.moved_prices` moves the order to the other side's touch once that long has passed since the clock started. `no_further_than` is the rule that keeps an ordinary step from going past the touch. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/chase_pricing/ChasePricing/example_2_crossing_when_time_is_up.py
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


class CrossingWhenTimeIsUpExample:
    """Prints a chasing sell's moves and the step limit."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        pricing = ChasePricing(2, 5.0, 12.0)
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        quotes = maker.book(1000.00, 1000.50)
        leg = maker.resting('SELL', 1000.50)
        memory = {}
        for now in (0.0, 6.0, 12.0):
            moved = pricing.moved_prices(plan_order, memory, leg, quotes, now)
            print(f'At {now} seconds: move {moved}')
            if moved is not None:
                leg.price = float(moved[0])
        print(f'A sell step to 999.90 with the bid at 1000.00 goes no further than {pricing.no_further_than(decimal.Decimal("999.90"), decimal.Decimal("1000.00"), "SELL")}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    CrossingWhenTimeIsUpExample().run()
