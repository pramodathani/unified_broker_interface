"""Shows marketable pricing declining to make a price when there is no book to price against, and a buffer of zero joining the touch.

`MarketablePricing` answers None when the quote has not arrived or the book has no opposite side, and the plan order then waits for the next tick rather than sending an order at a made-up price. A `buffer_ticks` of zero prices the limit exactly at the opposite touch.

A small stand-in plays the plan order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/marketable_pricing/MarketablePricing/example_2_no_book_no_price.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.marketable_pricing import (
    MarketablePricing,
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




class PricingExampleBody:
    """Builds the caller's order body the pricing examples price."""

    def body(self, transaction_type):
        """A limit order for ten RELIANCE shares at 1,000.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            dict: The body.
        """
        return {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': transaction_type,
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }


class NoBookNoPriceExample:
    """Prices a buy with no quote, with an empty offer side, and with a zero buffer.

    Attributes:
        plan_order (StandInPlanOrder): The stand-in plan order.
        quotes (QuoteBuilder): Builds the quote.
        bodies (PricingExampleBody): Builds the bodies.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = StandInPlanOrder()
        self.quotes = QuoteBuilder()
        self.bodies = PricingExampleBody()

    def run(self):
        """Prints each result.

        Returns:
            None: This method returns nothing.
        """
        pricing = MarketablePricing(2)
        print(f"No quote yet: {pricing.priced_body(self.plan_order, self.bodies.body('BUY'), 'BUY', {}, {})}")
        empty_offer = self.quotes.book_at(994.90, 994.95)
        empty_offer['depth']['sell'] = []
        quotes = {
            INSTRUMENT_ID: empty_offer,
        }
        print(f"No offers resting: {pricing.priced_body(self.plan_order, self.bodies.body('BUY'), 'BUY', quotes, {})}")
        joining = MarketablePricing(0)
        quotes = {
            INSTRUMENT_ID: self.quotes.book_at(994.90, 994.95),
        }
        body = joining.priced_body(self.plan_order, self.bodies.body('BUY'), 'BUY', quotes, {})
        print(f"Zero buffer: {body['order_type']} at {body['price']}; dry run shows {joining.described()}")
        print(f'Reads quotes: {joining.needs_prices()}')


if __name__ == '__main__':
    NoBookNoPriceExample().run()
