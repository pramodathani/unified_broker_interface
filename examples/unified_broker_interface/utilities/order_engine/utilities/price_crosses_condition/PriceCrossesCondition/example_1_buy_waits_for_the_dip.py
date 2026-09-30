"""Walks a price condition through ticks, showing the default direction and which part of the quote it reads.

A `PriceCrossesCondition` is the trigger a plan order waits on when it waits for a price. With no direction given, an order opened with a buy waits for the price to fall to the level, which is market-if-touched's meaning. This program asks one condition on the last price and one on the opposite touch, which for a buy is the best offer, the same questions on four ticks, and prints the answers, the direction each uses, and what a dry run shows for them.

A small stand-in plays the plan order, reading quotes with RELIANCE's tick size of 0.05. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_crosses_condition/PriceCrossesCondition/example_1_buy_waits_for_the_dip.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
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


class BuyWaitsForTheDipExample:
    """Asks two buy-side price conditions the same questions on four ticks.

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
        """Prints each condition's answer on each tick.

        Returns:
            None: This method returns nothing.
        """
        on_last = PriceCrossesCondition(decimal.Decimal('995'), None, 'last', None, 'none', None)
        on_touch = PriceCrossesCondition(decimal.Decimal('995'), None, 'opposite_touch', None, 'none', None)
        print(f"Direction for a buy: {on_last.effective_direction('BUY')}, for a sell: {on_last.effective_direction('SELL')}")
        print(f'Reads quotes: {on_last.needs_prices()}, watches other instruments: {on_last.instruments()}')
        on_last.prepare(self.plan_order, {})
        ticks = [
            ('steady', self.quotes.book_at(1000.00, 1000.05)),
            ('last trade 994.90, offer 995.10', self.quotes.book_at(994.95, 995.10, last_price=994.90)),
            ('offer down to 994.95', self.quotes.book_at(994.90, 994.95)),
            ('back up', self.quotes.book_at(1001.00, 1001.05)),
        ]
        for label, quote in ticks:
            quotes = {
                INSTRUMENT_ID: quote,
            }
            view = self.plan_order.view(quotes)
            last_met = on_last.is_met(self.plan_order, {}, quotes, 0.0, 'BUY', 'BUY')
            touch_met = on_touch.is_met(self.plan_order, {}, quotes, 0.0, 'BUY', 'BUY')
            print(f'{label}: last {on_last.watched_price(view, "BUY")} met {last_met}; offer {on_touch.watched_price(view, "BUY")} met {touch_met}')
        print(f'As a dry run shows them: {on_last.described()} and {on_touch.described()}')


if __name__ == '__main__':
    BuyWaitsForTheDipExample().run()
