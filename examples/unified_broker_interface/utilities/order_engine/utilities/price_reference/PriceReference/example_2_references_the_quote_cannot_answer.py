"""Shows the refusals `PriceReference.resolve` gives when the quote cannot answer a reference.

The order route is answering a caller who is waiting, so a price that cannot be worked out is refused with an HTTP status rather than guessed. This program builds a thin quote, with one level on each side and no volume weighted average price, and asks for references it cannot satisfy: a third level of the bids, the average price, any price with no quote at all, and an absolute price pushed below zero by a large negative offset.

Each refusal is a `RefusedRequestError` whose `status` and `body` are what the route sends back. A missing piece of the quote is a 503, because it may be there a second later, and a price that works out at zero or below is a 400, because the request itself is wrong. A plain `OrderRequest` does the tick rounding, and nothing is read from Redis.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_reference/PriceReference/example_2_references_the_quote_cannot_answer.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_reference import (
    PriceReference,
)


class UnanswerableReferencesExample:
    """Resolves references a thin quote cannot answer and prints each refusal.

    Attributes:
        resolver (PriceReference): The resolver being shown.
        tick_size (decimal.Decimal): The instrument's tick size.
        thin_quote (dict): A quote with only the touch and no average price.
        attempts (list): Triples of (reference, quote, side) to try.
    """

    def __init__(self):
        """Builds the resolver, the thin quote and the attempts.

        Returns:
            None: This method returns nothing.
        """
        self.resolver = PriceReference(OrderRequest())
        self.tick_size = decimal.Decimal('0.05')
        self.thin_quote = {
            'last_price': 42.35,
            'average_price': None,
            'depth': {
                'buy': [
                    {
                        'price': 42.3,
                        'quantity': 1000,
                        'orders': 2,
                    },
                ],
                'sell': [
                    {
                        'price': 42.4,
                        'quantity': 750,
                        'orders': 1,
                    },
                ],
            },
        }
        self.attempts = [
            (
                {
                    'kind': 'bid_level',
                    'level': 3,
                },
                self.thin_quote,
                'SELL',
            ),
            (
                {
                    'kind': 'vwap',
                },
                self.thin_quote,
                'BUY',
            ),
            (
                {
                    'kind': 'last',
                },
                None,
                'BUY',
            ),
            (
                {
                    'kind': 'absolute',
                    'price': decimal.Decimal('0.10'),
                    'offset_ticks': 5,
                },
                None,
                'SELL',
            ),
        ]

    def run(self):
        """Prints each attempt's refusal, and one reference the thin quote can answer.

        Returns:
            None: This method returns nothing.
        """
        for reference, quote, side in self.attempts:
            try:
                price = self.resolver.resolve(reference, quote, side, self.tick_size)
                print(f'{reference} {side}: {price}')
            except RefusedRequestError as error:
                print(f'{reference} {side}: refused with {error.status}: {error.body["error"]}')
        working = {
            'kind': 'marketable',
        }
        price = self.resolver.resolve(working, self.thin_quote, 'SELL', self.tick_size)
        print(f'{working} SELL: {price}')


if __name__ == '__main__':
    UnanswerableReferencesExample().run()
