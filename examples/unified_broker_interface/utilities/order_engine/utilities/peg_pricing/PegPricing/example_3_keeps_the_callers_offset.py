"""Shows a pegged buy keeping the distance from the bid that a caller chose through PUT /api/orders/modify, instead of snapping back to the plan's own offset.

The peg rests one tick under the bid. With the bid at 1000.00 the order rests at 999.95, and the caller moves it to 999.75. Without `carry_on`, the next tick would put it back one tick under the bid. `PegPricing.carry_on` reads the reference now with `reference_price`, works out that the caller's price is five ticks under it, and stores that in the memory as `offset_ticks`. From then on `offset` reads the caller's five ticks rather than the plan's one, so `moved_prices` keeps the order five ticks under the bid wherever the bid goes. A modify that leaves the price alone returns None.

A small stand-in plays the plan order with a tick of five paise. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/peg_pricing/PegPricing/example_3_keeps_the_callers_offset.py
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
    """Stands in for the plan order, which reads a quote into a market view and knows the tick size."""

    def tick_size(self):
        """The order's tick size, five paise.

        Returns:
            decimal.Decimal: The tick size.
        """
        return decimal.Decimal('0.05')

    def view(self, quotes):
        """The market, as the instrument's quote shows it.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(INSTRUMENT_ID), self.tick_size())


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


class KeepsTheCallersOffsetExample:
    """Moves a pegged buy as a caller would and follows the bid from the caller's distance."""

    def run(self):
        """Prints the change and the ticks after it.

        Returns:
            None: This method returns nothing.
        """
        pricing = PegPricing('own_touch', 1)
        plan_order = StandInPlanOrder()
        maker = QuoteMaker()
        memory = {}
        quotes = maker.book(1000.00, 1000.05)
        view = plan_order.view(quotes)
        leg = maker.resting('BUY', 999.95)
        print(f'Bid 1000.0: reference {pricing.reference_price(view, "BUY")}, offset {pricing.offset(memory)} tick, resting at {leg.price}')
        before = {
            'price': leg.price,
        }
        leg.price = 999.75
        print(f'The caller moves the price from {before["price"]} to {leg.price}')
        print(f'Without carry_on, the next tick moves it back: {pricing.moved_prices(plan_order, memory, leg, quotes, 0.0)}')
        print(f'carry_on: {pricing.carry_on(plan_order, memory, leg, before, quotes, 0.0)}')
        print(f'Memory: {memory}, offset now {pricing.offset(memory)} ticks')
        print(f'Wanted price with the caller\'s offset: {pricing.wanted_price(view, "BUY", pricing.offset(memory))}; with the plan\'s own: {pricing.wanted_price(view, "BUY")}')
        for bid, offer in ((1000.00, 1000.05), (1000.20, 1000.25), (999.80, 999.85)):
            moved = pricing.moved_prices(plan_order, memory, leg, maker.book(bid, offer), 0.0)
            print(f'Bid {bid}: move to {moved}')
            if moved is not None:
                leg.price = float(moved[0])
        unchanged = {
            'price': leg.price,
        }
        print(f'A modify that leaves the price alone: {pricing.carry_on(plan_order, memory, leg, unchanged, quotes, 0.0)}')


if __name__ == '__main__':
    KeepsTheCallersOffsetExample().run()
