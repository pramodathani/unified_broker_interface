"""Asks a limit_marketable trigger, tick by tick, whether a held buy at 1498.50 would now fill straight away.

`LimitMarketableCondition.is_met` reads the other side of the book: for a buy, the best offer. It holds once the offer is at or below the limit, and never on a quote marked stale, even one whose offer has reached the limit. For a sell it reads the best bid and holds once the bid is at or above the limit. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/limit_marketable_condition/LimitMarketableCondition/example_1_waiting_for_the_offer.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


class StandInContext:
    """Stands in for the order's view of the plan order: its body, and quotes read through `MarketView`.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's settings.
    """

    def __init__(self, body):
        """Builds the context.

        Args:
            body (dict): The order's settings.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'NSE:INFY'
        self.body = body

    def view(self, quotes, instrument_id=None):
        """The order's instrument's market, with a tick of 0.05.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): Unused, since only the order's own instrument is read.

        Returns:
            MarketView: The view.
        """
        del instrument_id
        return MarketView(quotes.get(self.instrument_id), decimal.Decimal('0.05'))


class WaitingForTheOfferExample:
    """Walks a buy and a sell through a few quotes."""

    def quote(self, bid, offer, stale=False):
        """A quote whose touch is at the given prices.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.
            stale (bool): Whether the quote is marked stale.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            'NSE:INFY': {
                'stale': stale,
                'depth': {
                    'buy': [
                        {
                            'price': bid,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': offer,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }

    def run(self):
        """Prints whether each quote releases the held orders.

        Returns:
            None: This method returns nothing.
        """
        condition = LimitMarketableCondition()
        print('described:', condition.described())
        print('needs prices:', condition.needs_prices(), 'watches others:', condition.instruments())
        buy = StandInContext({
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': '1498.50',
            'quantity': 20,
        })
        sell = StandInContext({
            'transaction_type': 'SELL',
            'order_type': 'LIMIT',
            'price': '1501.00',
            'quantity': 20,
        })
        steps = [
            ('offer above the buy limit', self.quote(1498.90, 1499.00)),
            ('offer reaches it, quote stale', self.quote(1498.40, 1498.50, stale=True)),
            ('offer reaches it', self.quote(1498.40, 1498.50)),
            ('bid reaches the sell limit', self.quote(1501.00, 1501.05)),
        ]
        for label, quotes in steps:
            buy_holds = condition.is_met(buy, {}, quotes, 0, 'BUY', 'BUY')
            sell_holds = condition.is_met(sell, {}, quotes, 0, 'SELL', 'SELL')
            print(f'{label}: buy releases {buy_holds}, sell releases {sell_holds}')


if __name__ == '__main__':
    WaitingForTheOfferExample().run()
