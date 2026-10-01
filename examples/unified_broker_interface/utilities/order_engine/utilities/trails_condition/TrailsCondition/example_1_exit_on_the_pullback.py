"""Walks an engine-side trailing condition for a long's exit through ticks, holding once the price falls five below its best.

A `TrailsCondition` is a trailing stop kept in the engine. For an order sent as a sell, it remembers the highest last price seen and holds once the price has fallen `points` below it. Because nothing rests at the broker, the order it triggers can be priced any way, for example as a marketable limit, which a native trailing stop cannot be.

A small stand-in plays the plan order, reading quotes with RELIANCE's tick size of 0.05. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trails_condition/TrailsCondition/example_1_exit_on_the_pullback.py
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


class ExitOnThePullbackExample:
    """Asks a five-point trailing condition for a sell on five ticks.

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
        """Prints the condition's answer and memory on each tick.

        Returns:
            None: This method returns nothing.
        """
        condition = TrailsCondition(decimal.Decimal('5'), None)
        memory = {}
        condition.prepare(self.plan_order, memory)
        print(f'Reads quotes: {condition.needs_prices()}, watches: {condition.instruments()}')
        for index, last in enumerate((1000.05, 1006.00, 1003.00, 1001.05, 1000.95)):
            quotes = {
                INSTRUMENT_ID: self.quotes.book_at(last - 0.05, last),
            }
            met = condition.is_met(self.plan_order, memory, quotes, float(index), 'BUY', 'SELL')
            print(f'last {last}: met {met}, memory {memory}')
        print(f'As a dry run shows it: {condition.described()}')


if __name__ == '__main__':
    ExitOnThePullbackExample().run()
