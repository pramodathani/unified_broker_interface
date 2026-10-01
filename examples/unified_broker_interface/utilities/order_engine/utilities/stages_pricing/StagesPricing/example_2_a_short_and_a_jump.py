"""Shows a stepped stop protecting a short, the limit it sits behind, and a jump straight past every milestone.

For a short the stop is a buy above the market, the gain is the entry less the price, and `limit_from` puts the limit above the trigger. A price that jumps past every milestone in one tick goes straight to the trailing rule. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/stages_pricing/StagesPricing/example_2_a_short_and_a_jump.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.stages_pricing import (
    StagesPricing,
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


class AShortAndAJumpExample:
    """Prints a short's stepped stop."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        rules = [
            {
                'gain': decimal.Decimal('20'),
                'stop_at_gain': decimal.Decimal('0'),
            },
            {
                'gain': decimal.Decimal('40'),
                'trail_points': decimal.Decimal('15'),
            },
        ]
        pricing = StagesPricing(decimal.Decimal('1000'), decimal.Decimal('1010'), decimal.Decimal('2'), 1, rules)
        plan_order = StandInPlanOrder()
        maker = StopMaker()
        print(f'A buy stop at 1010 has its limit at {pricing.limit_from(decimal.Decimal("1010"), "BUY")}')
        memory = {}
        leg = maker.stop('BUY', pricing.priced_body(plan_order, {'quantity': 10}, 'BUY', maker.last(999.95), memory))
        moved = pricing.moved_prices(plan_order, memory, leg, maker.last(955.00), 0.0)
        print(f'Last 955, a gain of {pricing.gain(decimal.Decimal("955"), "BUY")}: move {moved}')
        print(f'Memory: {memory}, so the trail is {pricing.trail(memory).described()}')


if __name__ == '__main__':
    AShortAndAJumpExample().run()
