"""Shows an average-range trailing stop carrying on from a trigger the caller moved through PUT /api/orders/modify, at whatever distance the bars give at that moment.

`AtrTrailPricing.carry_on` hands the change to an ordinary `TrailPricing` built at the distance `distance` gives now, which sets the best price so the trail lands exactly on the caller's trigger. The best price therefore depends on the bars. Before enough bars have closed the distance is `points`, 12 here, so a sell trigger of 990 means a best of 1002. The average needs one more closed bar than `periods`, so once three one-minute bars have closed, the last two with true ranges of 5 and 4, the distance is twice their average of 4.5, which is 9, and a caller who then moves the trigger from 990 to 985 sets a best of 994. On the next tick, `moved_prices` follows the market up from the caller's trigger rather than pulling the stop back to where it was.

A small stand-in plays the plan order with a tick of five paise, and a leg stands in for the resting stop. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/atr_trail_pricing/AtrTrailPricing/example_3_carries_on_from_the_callers_trigger.py
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

    def stop(self, side, trigger_price, price):
        """A resting stop on a side.

        Args:
            side (str): BUY or SELL, the side the stop trades.
            trigger_price (float): Its trigger.
            price (float): Its limit.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.trigger_price = trigger_price
        leg.price = price
        leg.quantity = 10
        leg.state = 'acknowledged'
        return leg

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
    """Moves an average-range trail's trigger as a caller would, before and after its bars have closed."""

    def run(self):
        """Prints each change and the tick after it.

        Returns:
            None: This method returns nothing.
        """
        pricing = AtrTrailPricing(decimal.Decimal('12'), decimal.Decimal('1'), 1, 1.0, 2, decimal.Decimal('2'))
        plan_order = StandInPlanOrder()
        maker = StopMaker()
        memory = {
            'best': '1012.00',
        }
        leg = maker.stop('SELL', 1000.00, 999.00)
        print(f'No bars yet, distance {pricing.distance(memory)}, resting trigger {leg.trigger_price}')
        before = maker.modified(leg, 990.00, 989.00)
        print(f'carry_on: {pricing.carry_on(plan_order, memory, leg, before, {}, 0.0)}')
        print(f'Best price now: {memory["best"]}')
        bars = pricing.bars(memory)
        for now, price in ((0, '1000'), (20, '1006'), (40, '998'), (60, '1001'), (80, '1003'), (120, '1000'), (140, '1004'), (180, '1002')):
            bars.add(decimal.Decimal(price), float(now))
        print(f'Three bars closed, distance {pricing.distance(memory)}')
        before = maker.modified(leg, 985.00, 984.00)
        print(f'The caller moves the trigger from {before["trigger_price"]} to {leg.trigger_price}')
        print(f'carry_on: {pricing.carry_on(plan_order, memory, leg, before, {}, 0.0)}')
        print(f'Best price now: {memory["best"]}')
        for now, price in ((185.0, 993.00), (190.0, 997.00)):
            moved = pricing.moved_prices(plan_order, memory, leg, maker.last(price), now)
            print(f'At {now} seconds, last {price}: best {memory["best"]}, move {moved}')


if __name__ == '__main__':
    CarriesOnFromTheCallersTriggerExample().run()
