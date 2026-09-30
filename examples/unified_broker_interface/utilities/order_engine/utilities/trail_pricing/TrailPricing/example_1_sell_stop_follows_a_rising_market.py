"""Places a trailing sell stop for a long and walks it through ticks: it follows the market up and never back down.

`TrailPricing` rests a native stop-limit and remembers the best last price seen in its memory. For a sell stop, protecting a long, the best is the highest price, and the trigger sits `points` below it with the limit `limit_offset` further. On every tick, `moved_prices` says where the stop should now be, or None when it should stay: when the market falls back, or when the move would be smaller than `step_ticks`.

A small stand-in plays the plan order, reading quotes with RELIANCE's tick size of 0.05, and a leg stands in for the resting stop. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trail_pricing/TrailPricing/example_1_sell_stop_follows_a_rising_market.py
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
FUTURE_ID = '11111111-1111-5111-8111-000000000004'


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


class SellStopFollowsARisingMarketExample:
    """Prices a trailing sell stop and moves it through four ticks.

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

    def run(self):
        """Prints the stop as placed and after each tick.

        Returns:
            None: This method returns nothing.
        """
        pricing = TrailPricing(decimal.Decimal('5'), None, decimal.Decimal('1'), 1)
        print(f'Reads quotes: {pricing.needs_prices()}, moves a resting order: {pricing.moves()}')
        memory = {}
        quotes = {
            INSTRUMENT_ID: self.quotes.book_at(1000.00, 1000.05),
        }
        body = pricing.priced_body(self.plan_order, {'transaction_type': 'SELL', 'quantity': 10}, 'SELL', quotes, memory)
        print(f"Placed at last 1000.05: {body['order_type']}, trigger {body['trigger_price']}, limit {body['price']}, memory {memory}")
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = 'SELL'
        leg.trigger_price = float(body['trigger_price'])
        for last in (1003.00, 1001.00, 1003.02, 1006.00):
            quotes = {
                INSTRUMENT_ID: self.quotes.book_at(last - 0.05, last),
            }
            moved = pricing.moved_prices(self.plan_order, memory, leg, quotes)
            print(f'last {last}: best {memory["best"]}, move {moved}')
            if moved is not None:
                leg.trigger_price = float(moved[1])
        print(f'Distance from a best of 1006: {pricing.distance(decimal.Decimal("1006"))}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    SellStopFollowsARisingMarketExample().run()
