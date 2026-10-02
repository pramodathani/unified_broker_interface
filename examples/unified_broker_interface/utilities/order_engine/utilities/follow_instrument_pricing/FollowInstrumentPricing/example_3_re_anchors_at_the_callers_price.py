"""Shows a Nifty call bid that follows the index re-anchoring at a price the caller set through PUT /api/orders/modify, instead of moving back.

The bid starts at 200 with the index at 25000 and a delta of 0.5, so when the index rises to 25040 the bid moves to 220. The caller then lowers it to 210. Without `carry_on`, the order would still be worked out from its first anchors, and the next tick would move it back to 220. `FollowInstrumentPricing.carry_on` replaces the anchors with the caller's price and the index now, so `start_price` becomes 210 and `watched_start` 25040. A tick with the index unchanged then leaves the order alone, and a rise of 40 to 25080 moves it 20, to 230. A modify that leaves the price alone returns None, and so does one made while the index has no price, which keeps the old anchors.

Small stand-ins play the plan order and the catalogue, with a tick of five paise. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/follow_instrument_pricing/FollowInstrumentPricing/example_3_re_anchors_at_the_callers_price.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.follow_instrument_pricing import (
    FollowInstrumentPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


OPTION_ID = '11111111-1111-5111-8111-000000000003'
INDEX_ID = '11111111-1111-5111-8111-000000000010'


class StandInParent:
    """Stands in for a plan order's parent.

    Attributes:
        instrument_id (str): The instrument the order trades.
        body (dict): The caller's body.
    """

    def __init__(self, instrument_id, body):
        """Builds the parent.

        Args:
            instrument_id (str): The instrument the order trades.
            body (dict): The caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.body = body


class StandInPlanOrder:
    """Stands in for the plan order a pricing is asked about.

    Attributes:
        parent (StandInParent): The parent.
        instrument_id (str): The instrument the order trades.
        body (dict): The caller's body.
    """

    def __init__(self, instrument_id, body):
        """Builds the stand-in.

        Args:
            instrument_id (str): The instrument the order trades.
            body (dict): The caller's body.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(instrument_id, body)
        self.instrument_id = instrument_id
        self.body = body

    def tick_size(self):
        """The order's tick size, five paise.

        Returns:
            decimal.Decimal: The tick size.
        """
        return decimal.Decimal('0.05')

    def view(self, quotes, instrument_id=None):
        """The market for an instrument, the order's own by default.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): The instrument, or None for the order's own.

        Returns:
            MarketView: The view.
        """
        wanted = instrument_id or self.parent.instrument_id
        return MarketView(quotes.get(wanted), self.tick_size())


class QuoteMaker:
    """Builds quotes and resting orders."""

    def index_at(self, price):
        """The quotes a tick carries with the index at a price.

        Args:
            price (float): The index's last price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INDEX_ID: {
                'last_price': price,
            },
        }

    def resting(self, side, price):
        """A resting broker order.

        Args:
            side (str): BUY or SELL.
            price (float): Its limit.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.price = price
        leg.quantity = 75
        leg.state = 'acknowledged'
        return leg


class ReAnchorsAtTheCallersPriceExample:
    """Follows the index with a call bid, through a caller's change.

    Attributes:
        body (dict): The caller's body, a limit buy at 200.
        pricing (FollowInstrumentPricing): The pricing, following the index with a delta of 0.5.
        plan_order (StandInPlanOrder): The stand-in plan order.
        maker (QuoteMaker): Builds quotes and the leg.
    """

    def __init__(self):
        """Builds the pricing and the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'order_type': 'LIMIT',
            'price': 200,
        }
        self.pricing = FollowInstrumentPricing(INDEX_ID, decimal.Decimal('0.5'), None, None, 20)
        self.plan_order = StandInPlanOrder(OPTION_ID, self.body)
        self.maker = QuoteMaker()

    def tick(self, memory, leg, index):
        """Sends one tick through the pricing, prints the answer and follows any move.

        Args:
            memory (dict): The pricing's memory.
            leg (OrderLeg): The resting order.
            index (float): The index's last price.

        Returns:
            None: This method returns nothing.
        """
        moved = self.pricing.moved_prices(self.plan_order, memory, leg, self.maker.index_at(index), 0.0)
        print(f'Index {index}: move {moved}')
        if moved is not None:
            leg.price = float(moved[0])

    def run(self):
        """Prints each tick and the change.

        Returns:
            None: This method returns nothing.
        """
        memory = {}
        self.pricing.priced_body(self.plan_order, dict(self.body), 'BUY', self.maker.index_at(25000), memory)
        print(f'Sent at 200, remembering {memory}')
        leg = self.maker.resting('BUY', 200)
        self.tick(memory, leg, 25040)
        before = {
            'price': leg.price,
        }
        leg.price = 210.0
        print(f'The caller moves the price from {before["price"]} to {leg.price}')
        untouched_memory = dict(memory)
        print(f'Without carry_on, index 25040: {self.pricing.moved_prices(self.plan_order, untouched_memory, leg, self.maker.index_at(25040), 0.0)}')
        print(f'With no index price: {self.pricing.carry_on(self.plan_order, memory, leg, before, {}, 0.0)}, memory {memory}')
        print(f'carry_on: {self.pricing.carry_on(self.plan_order, memory, leg, before, self.maker.index_at(25040), 0.0)}')
        print(f'Memory now: {memory}')
        self.tick(memory, leg, 25040)
        self.tick(memory, leg, 25080)
        unchanged = {
            'price': leg.price,
        }
        print(f'A modify that leaves the price alone: {self.pricing.carry_on(self.plan_order, memory, leg, unchanged, self.maker.index_at(25080), 0.0)}')


if __name__ == '__main__':
    ReAnchorsAtTheCallersPriceExample().run()
