"""Shows a trailing condition given as a percentage, for an order sent as a buy, which follows the lowest price and holds on a rise.

For an order sent as a buy, such as the exit of a short or an entry on a rebound, a `TrailsCondition` remembers the lowest last price seen and holds once the price has risen the distance above it. With `percent`, the distance is that share of the lowest price. `improves` says whether a price is better than the best for an order sent on a given side. With no last price, the condition cannot hold.

A small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trails_condition/TrailsCondition/example_2_percent_for_a_buy.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.trails_condition import (
    TrailsCondition,
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


class PercentForABuyExample:
    """Asks a half per cent trailing condition for a buy on four ticks.

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
        """Prints the condition's answer on each tick.

        Returns:
            None: This method returns nothing.
        """
        condition = TrailsCondition(None, decimal.Decimal('0.5'))
        print(f'With no quote: {condition.is_met(self.plan_order, {}, {}, 0.0, "SELL", "BUY")}')
        print(f"990 improves on 1000 for a buy: {condition.improves(decimal.Decimal('990'), decimal.Decimal('1000'), 'BUY')}; for a sell: {condition.improves(decimal.Decimal('990'), decimal.Decimal('1000'), 'SELL')}")
        memory = {}
        for index, last in enumerate((1000.00, 990.00, 994.00, 995.00)):
            quotes = {
                INSTRUMENT_ID: self.quotes.book_at(last - 0.05, last),
            }
            met = condition.is_met(self.plan_order, memory, quotes, float(index), 'SELL', 'BUY')
            print(f'last {last}: met {met}, lowest {memory["best"]}')
        print(f'As a dry run shows it: {condition.described()}')


if __name__ == '__main__':
    PercentForABuyExample().run()
