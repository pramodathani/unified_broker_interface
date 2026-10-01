"""Walks a sell stop trailing twice the average range of one-minute bars, needing two bars, through a rising market.

`AtrTrailPricing.priced_body` rests the stop `points` behind the last price, because no bars have closed. `moved_prices` adds each tick's price to the bars kept in memory, and once two bars have closed, `distance` is the average true range times the multiple instead of `points`. The stop then trails as an ordinary `TrailPricing` built by `trail`. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/atr_trail_pricing/AtrTrailPricing/example_1_fallback_then_the_average.py
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


class FallbackThenTheAverageExample:
    """Walks an average-range trail through its bars."""

    def run(self):
        """Prints each tick.

        Returns:
            None: This method returns nothing.
        """
        pricing = AtrTrailPricing(decimal.Decimal('10'), decimal.Decimal('2'), 1, 1.0, 2, decimal.Decimal('1'))
        plan_order = StandInPlanOrder()
        maker = StopMaker()
        print(f'Reads quotes: {pricing.needs_prices()}, moves: {pricing.moves()}')
        memory = {}
        body = pricing.priced_body(plan_order, {'quantity': 10}, 'SELL', maker.last(1000.05), memory)
        print(f'Sent as: {body}')
        leg = maker.stop('SELL', body)
        for now, price in ((10, 1040.05), (70, 1010.05), (130, 1060.05), (190, 1080.05)):
            moved = pricing.moved_prices(plan_order, memory, leg, maker.last(price), float(now))
            print(f'At {now} seconds, last {price}: distance {pricing.distance(memory)}, move {moved}')
            maker.follow(leg, moved)
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    FallbackThenTheAverageExample().run()
