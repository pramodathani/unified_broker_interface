"""Shows the bars an average-range trail keeps in its memory, and the plain trail it hands each tick to.

`AtrTrailPricing.bars` is a `BarBuilder` over the `bars` dictionary in the pricing's memory, so the bars survive in the part's record. Each bar's true range needs the close of the bar before it, so an average over two periods needs three closed bars: with two, `distance` still answers the `points` fallback of 8, and once a third bar closes it answers the average of the last two true ranges, 5 and 9, times the multiple of 2, which is 14. `trail` builds the ordinary trail at a given distance. A buy stop, protecting a short, trails the lowest price down. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/atr_trail_pricing/AtrTrailPricing/example_2_bars_in_memory.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.atr_trail_pricing import (
    AtrTrailPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInPlanOrder:
    """Stands in for the plan order a pricing is asked about."""

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


class StopMaker:
    """Builds quotes and the resting stop."""

    def last(self, price):
        """The quotes a tick carries with a last price.

        Args:
            price (float): The last traded price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INSTRUMENT_ID: {
                'last_price': price,
            },
        }

    def stop(self, side, body):
        """The resting stop a priced body was sent as.

        Args:
            side (str): BUY or SELL, the side the stop trades.
            body (dict): The priced body.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.trigger_price = float(body['trigger_price'])
        leg.price = float(body['price'])
        leg.quantity = 10
        leg.state = 'acknowledged'
        return leg

    def follow(self, leg, moved):
        """Moves the leg as the broker would once a move is accepted.

        Args:
            leg (OrderLeg): The resting stop.
            moved (tuple | None): The move, or None.

        Returns:
            None: This method returns nothing.
        """
        if moved is not None:
            leg.price = float(moved[0])
            leg.trigger_price = float(moved[1])


class BarsInMemoryExample:
    """Prints the bars and the trail a buy stop uses."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        pricing = AtrTrailPricing(decimal.Decimal('8'), decimal.Decimal('1'), 1, 1.0, 2, decimal.Decimal('2'))
        memory = {}
        bars = pricing.bars(memory)
        for now, price in ((0, '1000'), (20, '1006'), (40, '998'), (60, '1001'), (80, '1003'), (120, '1000')):
            bars.add(decimal.Decimal(price), float(now))
        print(f'Bars kept: {memory["bars"]}')
        print(f'Distance with two closed bars, still the points fallback: {pricing.distance(memory)}')
        for now, price in ((150, '1009'), (180, '1004')):
            bars.add(decimal.Decimal(price), float(now))
        print(f'Closed bars now: {memory["bars"]["closed_bars"]}')
        print(f'Distance with three closed bars, the average range times 2: {pricing.distance(memory)}')
        print(f'The trail it hands to: {pricing.trail(decimal.Decimal("12")).described()}')
        plan_order = StandInPlanOrder()
        body = pricing.priced_body(plan_order, {'quantity': 10}, 'BUY', StopMaker().last(990.00), {})
        print(f'A buy stop with no bars is sent as: {body}')


if __name__ == '__main__':
    BarsInMemoryExample().run()
