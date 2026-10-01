"""Walks a stop protecting a long bought at 1000 through its milestones: breakeven at 20 in profit, 15 locked in at 40, and a 25-point trail from 60.

`StagesPricing.priced_body` rests the stop at `stop_price`. `moved_prices` measures the `gain` from the entry, moves the stop to each milestone as it is reached, never loosening it, and at the trailing rule hands the rest of the trade to the `TrailPricing` that `trail` builds. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/stages_pricing/StagesPricing/example_1_milestones_then_a_trail.py
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


class MilestonesThenATrailExample:
    """Walks a stepped stop through its milestones."""

    def run(self):
        """Prints each tick.

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
                'stop_at_gain': decimal.Decimal('15'),
            },
            {
                'gain': decimal.Decimal('60'),
                'trail_points': decimal.Decimal('25'),
            },
        ]
        pricing = StagesPricing(decimal.Decimal('1000'), decimal.Decimal('990'), decimal.Decimal('2'), 1, rules)
        plan_order = StandInPlanOrder()
        maker = StopMaker()
        print(f'Reads quotes: {pricing.needs_prices()}, moves: {pricing.moves()}')
        memory = {}
        body = pricing.priced_body(plan_order, {'quantity': 10}, 'SELL', maker.last(1000.05), memory)
        print(f'Sent as: {body}')
        leg = maker.stop('SELL', body)
        for price in (1025.00, 1045.00, 1030.00, 1070.00, 1080.00):
            moved = pricing.moved_prices(plan_order, memory, leg, maker.last(price), 0.0)
            print(f'Last {price}, gain {pricing.gain(decimal.Decimal(str(price)), "SELL")}: move {moved}')
            maker.follow(leg, moved)
        print(f'Memory: {memory}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    MilestonesThenATrailExample().run()
