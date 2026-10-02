"""Shows a trailing sell stop carrying on from a trigger the caller loosened through PUT /api/orders/modify, instead of snapping back.

A sell stop trailing 5 points behind has followed the market to a best of 1006, so its trigger rests at 1001. The caller then loosens the trigger to 995. The trail's memory still says the best price is 1006, so on the next tick `moved_prices` would pull the stop straight back to 1001. `TrailPricing.carry_on` prevents that by setting the best price to the one whose trail lands exactly on the caller's trigger, which `best_for_trigger` works out: 1000 for a 5-point trail. From there the stop follows the market up again as usual. When the trigger did not change, `carry_on` returns None and leaves the memory alone.

The second half does the same for a trail of one per cent, where `best_for_trigger` divides rather than adds: a sell trigger of 994.95 comes from a best of 1005, and a buy trigger of 1015.05 from the same best of 1005.

A small stand-in plays the plan order, reading quotes with RELIANCE's tick size of 0.05, and a leg stands in for the resting stop. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trail_pricing/TrailPricing/example_3_carries_on_from_the_callers_trigger.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.trail_pricing import (
    TrailPricing,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class QuoteBuilder:
    """Builds live quotes in the shape `unified:quotes:live` holds them, with five levels behind each side."""

    def book_at(self, bid, offer, last_price=None):
        """A quote whose best bid and offer sit where the program wants them.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.
            last_price (float | None): The last traded price, or None for the offer.

        Returns:
            dict: The quote.
        """
        buy_levels = []
        sell_levels = []
        for index in range(5):
            buy_levels.append({
                'price': round(bid - index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
            sell_levels.append({
                'price': round(offer + index * 0.05, 2),
                'quantity': 100,
                'orders': 1,
            })
        return {
            'last_price': last_price if last_price is not None else offer,
            'average_price': 999.80,
            'previous_close': 995.00,
            'depth': {
                'buy': buy_levels,
                'sell': sell_levels,
            },
        }


class StandInParent:
    """Stands in for the plan order's parent, holding the caller's body.

    Attributes:
        body (dict): The caller's order body.
    """

    def __init__(self, transaction_type):
        """Builds the parent for an order of ten RELIANCE shares.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': transaction_type,
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }


class StandInPlanOrder:
    """Stands in for the plan order, reading quotes with RELIANCE's tick size of 0.05 on the NSE.

    Attributes:
        parent (StandInParent): The parent, holding the caller's body.
    """

    def __init__(self, transaction_type='BUY'):
        """Builds the stand-in.

        Args:
            transaction_type (str): The side of the caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(transaction_type)

    def view(self, quotes, instrument_id=None):
        """One instrument's quote as a market view.

        Args:
            quotes (dict): Quotes by instrument id.
            instrument_id (str | None): The instrument, or None for RELIANCE.

        Returns:
            MarketView: The view.
        """
        wanted = instrument_id or INSTRUMENT_ID
        return MarketView(quotes.get(wanted), decimal.Decimal('0.05'))

    def trading_segment(self):
        """The segment RELIANCE trades on.

        Returns:
            str: `nse_equities`.
        """
        return 'nse_equities'

    def tick_size(self):
        """RELIANCE's tick size.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')


class CarriesOnFromTheCallersTriggerExample:
    """Loosens a trailing stop's trigger as a caller would, and shows the trail carrying on from it.

    Attributes:
        plan_order (StandInPlanOrder): The stand-in plan order.
        quotes (QuoteBuilder): Builds the ticks' quotes.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = StandInPlanOrder()
        self.quotes = QuoteBuilder()

    def resting_stop(self, side, trigger_price, price):
        """The stop as it rests at the broker.

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

    def last_at(self, last):
        """The quotes a tick carries with RELIANCE last traded at a price.

        Args:
            last (float): The last traded price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INSTRUMENT_ID: self.quotes.book_at(last - 0.05, last),
        }

    def run_points(self):
        """Prints the 5-point trail before and after the caller loosens its trigger.

        Returns:
            None: This method returns nothing.
        """
        pricing = TrailPricing(decimal.Decimal('5'), None, decimal.Decimal('1'), 1)
        memory = {
            'best': '1006.00',
        }
        leg = self.resting_stop('SELL', 1001.00, 1000.00)
        print(f'Resting: trigger {leg.trigger_price}, limit {leg.price}, memory {memory}')
        before = {
            'trigger_price': leg.trigger_price,
            'price': leg.price,
        }
        leg.trigger_price = 995.00
        leg.price = 994.00
        print(f'The caller moves the trigger from {before["trigger_price"]} to {leg.trigger_price}')
        untouched_memory = dict(memory)
        print(f'Without carry_on, last 1003.0 would move it back: {pricing.moved_prices(self.plan_order, untouched_memory, leg, self.last_at(1003.00), 0.0)}')
        print(f'Best price for a sell trigger of 995: {pricing.best_for_trigger(decimal.Decimal("995"), "SELL")}')
        message = pricing.carry_on(self.plan_order, memory, leg, before, {}, 0.0)
        print(f'carry_on: {message}')
        print(f'Memory now: {memory}')
        for last in (999.00, 1003.00):
            moved = pricing.moved_prices(self.plan_order, memory, leg, self.last_at(last), 0.0)
            print(f'last {last}: best {memory["best"]}, move {moved}')
            if moved is not None:
                leg.price = float(moved[0])
                leg.trigger_price = float(moved[1])
        unchanged = {
            'trigger_price': leg.trigger_price,
            'price': leg.price,
        }
        print(f'A modify that leaves the trigger alone: {pricing.carry_on(self.plan_order, memory, leg, unchanged, {}, 0.0)}')

    def run_percent(self):
        """Prints the one per cent trail carrying on from a caller's trigger.

        Returns:
            None: This method returns nothing.
        """
        pricing = TrailPricing(None, decimal.Decimal('1'), decimal.Decimal('1'), 1)
        print(f'One per cent trail, best price for a sell trigger of 994.95: {pricing.best_for_trigger(decimal.Decimal("994.95"), "SELL")}')
        print(f'One per cent trail, best price for a buy trigger of 1015.05: {pricing.best_for_trigger(decimal.Decimal("1015.05"), "BUY")}')
        memory = {
            'best': '1020.00',
        }
        leg = self.resting_stop('SELL', 1009.80, 1008.80)
        before = {
            'trigger_price': leg.trigger_price,
            'price': leg.price,
        }
        leg.trigger_price = 994.95
        leg.price = 993.95
        print(f'carry_on from {before["trigger_price"]} to {leg.trigger_price}: {pricing.carry_on(self.plan_order, memory, leg, before, {}, 0.0)}')
        moved = pricing.moved_prices(self.plan_order, memory, leg, self.last_at(1010.00), 0.0)
        print(f'last 1010.0: best {memory["best"]}, move {moved}')

    def run(self):
        """Prints both stories.

        Returns:
            None: This method returns nothing.
        """
        self.run_points()
        self.run_percent()


if __name__ == '__main__':
    CarriesOnFromTheCallersTriggerExample().run()
