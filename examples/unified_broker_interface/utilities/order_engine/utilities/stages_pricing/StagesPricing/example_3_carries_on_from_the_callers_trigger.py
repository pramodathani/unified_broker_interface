"""Shows a stepped stop keeping a caller's trigger before its trail begins, and carrying the trail on from the caller's trigger after.

The stop protects a long bought at 1000, with breakeven at 20 in profit, 15 locked in at 40, and a 25-point trail from 60. After the first milestone the stop rests at 1000, and the caller moves it to 1005 through PUT /api/orders/modify. `StagesPricing.carry_on` returns None and changes nothing, because the milestones are measured from the entry, not from the stop: the caller's trigger simply stands until the next milestone moves the stop further, to 1015.

Once the trailing rule has taken over, the memory holds `trail_points`, and `carry_on` hands the change to the trail. When the caller loosens the trigger from 1045 to 1035, the trail's best price becomes 1060, so the next tick follows the market up from the caller's trigger instead of snapping back to 1045.

A small stand-in plays the plan order with a tick of five paise, and a leg stands in for the resting stop. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/stages_pricing/StagesPricing/example_3_carries_on_from_the_callers_trigger.py
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

    def modified(self, leg, trigger_price, price):
        """Applies a caller's modify to the leg and returns what it held before.

        Args:
            leg (OrderLeg): The resting stop, changed in place.
            trigger_price (float): The caller's new trigger.
            price (float): The caller's new limit.

        Returns:
            dict: The trigger and limit the leg held before the change.
        """
        before = {
            'trigger_price': leg.trigger_price,
            'price': leg.price,
        }
        leg.trigger_price = trigger_price
        leg.price = price
        return before


class CarriesOnFromTheCallersTriggerExample:
    """Moves a stepped stop's trigger as a caller would, before and after its trail begins.

    Attributes:
        pricing (StagesPricing): The stepped stop.
        plan_order (StandInPlanOrder): The stand-in plan order.
        maker (StopMaker): Builds quotes and the leg.
    """

    def __init__(self):
        """Builds the stepped stop and the stand-ins.

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
        self.pricing = StagesPricing(decimal.Decimal('1000'), decimal.Decimal('990'), decimal.Decimal('2'), 1, rules)
        self.plan_order = StandInPlanOrder()
        self.maker = StopMaker()

    def tick(self, memory, leg, price):
        """Sends one tick through the pricing, prints the answer and follows any move.

        Args:
            memory (dict): The pricing's memory.
            leg (OrderLeg): The resting stop.
            price (float): The last traded price.

        Returns:
            None: This method returns nothing.
        """
        moved = self.pricing.moved_prices(self.plan_order, memory, leg, self.maker.last(price), 0.0)
        print(f'Last {price}: move {moved}')
        self.maker.follow(leg, moved)

    def run(self):
        """Prints each tick and each change.

        Returns:
            None: This method returns nothing.
        """
        memory = {}
        body = {
            'quantity': 10,
        }
        body = self.pricing.priced_body(self.plan_order, body, 'SELL', self.maker.last(1000.05), memory)
        leg = self.maker.stop('SELL', body)
        self.tick(memory, leg, 1025.00)
        before = self.maker.modified(leg, 1005.00, 1003.00)
        print(f'The caller moves the trigger from {before["trigger_price"]} to {leg.trigger_price}')
        print(f'carry_on before the trail: {self.pricing.carry_on(self.plan_order, memory, leg, before, {}, 0.0)}, memory {memory}')
        self.tick(memory, leg, 1030.00)
        self.tick(memory, leg, 1045.00)
        self.tick(memory, leg, 1070.00)
        print(f'Memory once trailing: {memory}')
        before = self.maker.modified(leg, 1035.00, 1033.00)
        print(f'The caller moves the trigger from {before["trigger_price"]} to {leg.trigger_price}')
        print(f'carry_on while trailing: {self.pricing.carry_on(self.plan_order, memory, leg, before, {}, 0.0)}')
        print(f'Memory now: {memory}')
        self.tick(memory, leg, 1062.00)
        self.tick(memory, leg, 1065.00)


if __name__ == '__main__':
    CarriesOnFromTheCallersTriggerExample().run()
