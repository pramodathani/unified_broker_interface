"""Shows a trailing distance given as a percentage, and a buy stop that follows a falling market down.

`TrailPricing` takes its distance as `points` or as `percent` of the best price seen, which widens as the trade goes the caller's way. A buy stop, as in a trailing entry or the protection of a short, sits above the market and follows the lowest price down. `improves` says whether a price is better than the best for a stop on a given side, and `prices_from` gives the trigger and limit for a best price, rounded onto the tick. With no last price yet, no stop can be priced.

A small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trail_pricing/TrailPricing/example_2_percent_and_a_buy_stop.py
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


class PercentAndABuyStopExample:
    """Prices a one per cent trailing buy stop and moves it down.

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
        """Prints the stop as placed and after two ticks.

        Returns:
            None: This method returns nothing.
        """
        pricing = TrailPricing(None, decimal.Decimal('1'), decimal.Decimal('2'), 2)
        print(f'No quote yet: {pricing.priced_body(self.plan_order, {"transaction_type": "BUY", "quantity": 10}, "BUY", {}, {})}')
        memory = {}
        quotes = {
            INSTRUMENT_ID: self.quotes.book_at(1000.00, 1000.05),
        }
        body = pricing.priced_body(self.plan_order, {'transaction_type': 'BUY', 'quantity': 10}, 'BUY', quotes, memory)
        print(f"Buy stop at last 1000.05: trigger {body['trigger_price']}, limit {body['price']}")
        print(f"990 improves on 1000 for a buy stop: {pricing.improves(decimal.Decimal('990'), decimal.Decimal('1000'), 'BUY')}; for a sell stop: {pricing.improves(decimal.Decimal('990'), decimal.Decimal('1000'), 'SELL')}")
        view = self.plan_order.view(quotes)
        print(f"Prices from a best of 990 for a buy stop: {pricing.prices_from(view, decimal.Decimal('990'), 'BUY')}")
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = 'BUY'
        leg.trigger_price = float(body['trigger_price'])
        for last in (999.95, 990.00):
            quotes = {
                INSTRUMENT_ID: self.quotes.book_at(last - 0.05, last),
            }
            print(f'last {last}: move {pricing.moved_prices(self.plan_order, memory, leg, quotes)}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    PercentAndABuyStopExample().run()
