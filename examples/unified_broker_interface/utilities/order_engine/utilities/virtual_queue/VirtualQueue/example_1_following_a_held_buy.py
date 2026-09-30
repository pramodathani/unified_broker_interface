"""Follows one held buy order's place in the queue as quotes go past, until the offer comes down to its price.

A `VirtualQueue` estimates where a limit order would stand if it had been resting at the exchange. This program holds a buy of 500 at 98.00 and feeds it five quotes, written as plain dictionaries in the unified quote shape. The first quote only sets the baseline, so the order joins the back of the 1,200 already bid at 98.00. The next quotes show trades at 98.00, which serve the queue ahead first, and a cancellation, which shortens the queue ahead in proportion. The last quote shows the offer at 98.00, which is the moment the engine would send the real order.

Nothing here needs Redis or a broker: the class only reads the quotes it is given. Notice that `queue_filled` counts only what the queue would have given, while `filled` jumps to the whole order once the touch is recorded, and that the stored document carries both. The two "remaining" numbers differ on purpose: the `remaining()` method is what the queue has not filled yet, while the document's `remaining` is what is left after `filled`, which is nothing once the touch is recorded. A stale quote at the end is ignored.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_queue/VirtualQueue/example_1_following_a_held_buy.py
"""

import decimal
import json

from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)


class HeldBuyExample:
    """Feeds a held buy order a short run of quotes and prints its estimated place after each.

    Attributes:
        estimate (VirtualQueue): The estimate being shown.
        quotes (list): The unified quotes fed in, oldest first.
    """

    def __init__(self):
        """Builds a buy of 500 at 98.00 and the quotes to feed it.

        Returns:
            None: This method returns nothing.
        """
        self.estimate = VirtualQueue(
            'parent-1',
            'NSE:INFY',
            'BUY',
            decimal.Decimal('98'),
            500,
        )
        self.quotes = [
            self.quote(1000, 98.05, 1200, 98.10, 1759200000.0),
            self.quote(1700, 98.00, 900, 98.10, 1759200001.0),
            self.quote(1900, 98.00, 500, 98.05, 1759200002.0),
            self.quote(2300, 98.00, 300, 98.05, 1759200003.0),
            self.quote(2300, 98.00, 300, 98.00, 1759200004.0),
        ]

    def quote(self, volume, last_price, bid_quantity, offer_price, received_at):
        """Builds one unified quote with two bid levels and one offer level.

        Args:
            volume (int): The day's volume so far.
            last_price (float): The last traded price.
            bid_quantity (int): The quantity bid at 98.00.
            offer_price (float): The best offer.
            received_at (float): When the quote arrived, as epoch seconds.

        Returns:
            dict: The quote.
        """
        return {
            'broker': 'zerodha',
            'volume': volume,
            'last_price': last_price,
            'received_at': received_at,
            'stale': False,
            'depth': {
                'buy': [
                    {
                        'price': 98.00,
                        'quantity': bid_quantity,
                    },
                    {
                        'price': 97.95,
                        'quantity': 4000,
                    },
                ],
                'sell': [
                    {
                        'price': offer_price,
                        'quantity': 700,
                    },
                ],
            },
        }

    def run(self):
        """Feeds every quote and prints the estimate after each, then the stored document.

        Returns:
            None: This method returns nothing.
        """
        for quote in self.quotes:
            changed = self.estimate.update(quote)
            print(
                f'volume {quote["volume"]}, bid at 98 {quote["depth"]["buy"][0]["quantity"]}, offer {quote["depth"]["sell"][0]["price"]}: '
                f'changed={changed} ahead={self.estimate.ahead} queue_filled={self.estimate.queue_filled} '
                f'filled={self.estimate.filled()} remaining={self.estimate.remaining()} touched_at={self.estimate.touched_at}'
            )
        stale_quote = self.quote(9999, 97.00, 0, 97.00, 1759200005.0)
        stale_quote['stale'] = True
        print(f'A stale quote changes it: {self.estimate.update(stale_quote)}')
        print(json.dumps(self.estimate.document(), indent=2))


if __name__ == '__main__':
    HeldBuyExample().run()
