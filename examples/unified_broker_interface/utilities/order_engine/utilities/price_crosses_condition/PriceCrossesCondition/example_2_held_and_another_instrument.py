"""Shows a price condition that must hold for five seconds, and one that watches another instrument.

A `PriceCrossesCondition` with `confirm` set to `held` fires only once the level has stayed reached for `hold_seconds`, keeping the time it was first reached in its memory between ticks; a tick that does not reach the level starts the count again. One with an `instrument_id` watches that instrument instead of the order's own, as cross-instrument orders do, and says so through `instruments`, which is how the price ticker knows to fetch its quote.

A small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_crosses_condition/PriceCrossesCondition/example_2_held_and_another_instrument.py
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


class HeldAndAnotherInstrumentExample:
    """Runs a held condition and a cross-instrument condition through ticks.

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
        held = PriceCrossesCondition(decimal.Decimal('995'), None, 'last', None, 'held', decimal.Decimal('5'))
        memory = {}
        below = self.quotes.book_at(994.85, 994.90)
        above = self.quotes.book_at(1000.00, 1000.05)
        for seconds, quote in ((1, below), (3, below), (4, above), (5, below), (8, below), (10, below)):
            quotes = {
                INSTRUMENT_ID: quote,
            }
            met = held.is_met(self.plan_order, memory, quotes, float(seconds), 'BUY', 'BUY')
            print(f'second {seconds}: last {quote["last_price"]}, met {met}, memory {memory}')
        watching = PriceCrossesCondition(decimal.Decimal('1010'), 'at_or_above', 'last', FUTURE_ID, 'none', None)
        print(f'Watches: {watching.instruments()}')
        for future_price in (1004.30, 1010.30):
            quotes = {
                INSTRUMENT_ID: above,
                FUTURE_ID: self.quotes.book_at(future_price - 0.2, future_price),
            }
            met = watching.is_met(self.plan_order, {}, quotes, 0.0, 'BUY', 'BUY')
            print(f'future at {future_price}: met {met}')


if __name__ == '__main__':
    HeldAndAnotherInstrumentExample().run()
