"""Shows where a midpoint peg and a peg to the opposite touch sit, and a book that cannot be priced yet.

`PegPricing.wanted_price` reads the reference from the book and rounds it onto the tick on the passive side, so a midpoint that falls between two ticks rests on the side away from filling. A book with no offer cannot give a midpoint, so nothing is priced. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_2_mid_and_opposite_touch.py
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


class MidAndOppositeTouchExample:
    """Prints the prices of pegs to the midpoint and to the other side's touch."""

    def run(self):
        """Prints each price.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        quotes = maker.book(1000.00, 1000.15)
        view = plan_order.view(quotes)
        mid = PegPricing('mid', 0)
        opposite = PegPricing('opposite_touch', 0)
        print(f'Midpoint peg, buy: {mid.wanted_price(view, "BUY")}, sell: {mid.wanted_price(view, "SELL")}')
        print(f'Opposite touch peg, buy: {opposite.wanted_price(view, "BUY")}, sell: {opposite.wanted_price(view, "SELL")}')
        one_sided = {
            INSTRUMENT_ID: {
                'depth': {
                    'buy': [
                        {
                            'price': 1000.00,
                            'quantity': 100,
                        },
                    ],
                    'sell': [],
                },
            },
        }
        print(f'With no offer, the midpoint peg sends: {mid.priced_body(plan_order, {}, "BUY", one_sided, {})}')
        print(f'As a dry run shows them: {mid.described()} and {opposite.described()}')


if __name__ == '__main__':
    MidAndOppositeTouchExample().run()
