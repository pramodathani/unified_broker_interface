"""Shows the refusals `QuantityReference.resolve` gives when there is nothing to close or the positions cannot be read.

Closing a position the caller does not hold would open a new one the other way, so `QuantityReference` refuses rather than guessing. This program asks for four things that cannot be done: liquidating an instrument with no open position (its long and short rows net to zero), reducing a position when the positions document is missing, reading a document that carries no `net` rows, and an `absolute` reference with a quantity of zero.

Each refusal is a `RefusedRequestError` whose `status` and `body` are what the order route sends back: 409 when there is no position, 503 when the positions cannot be read, and 400 when the caller's own quantity is wrong. Every document is written by hand, so nothing is read from Redis.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/quantity_reference/QuantityReference/example_2_nothing_to_close.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.quantity_reference import (
    QuantityReference,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'


class NothingToCloseExample:
    """Resolves quantity references that cannot be answered and prints each refusal.

    Attributes:
        resolver (QuantityReference): The resolver being shown.
        attempts (list): Quadruples of (description, reference, positions, requested quantity).
    """

    def __init__(self):
        """Builds the resolver and the attempts.

        Returns:
            None: This method returns nothing.
        """
        self.resolver = QuantityReference()
        flat_positions = {
            'net': [
                {
                    'instrument_id': RELIANCE,
                    'product': 'intraday',
                    'quantity': 40,
                },
                {
                    'instrument_id': RELIANCE,
                    'product': 'intraday',
                    'quantity': -40,
                },
            ],
            'day': [],
        }
        self.attempts = [
            (
                'liquidate a flat position',
                {
                    'kind': 'liquidate_position',
                },
                flat_positions,
                0,
            ),
            (
                'reduce with no positions document',
                {
                    'kind': 'reduce_position',
                },
                None,
                10,
            ),
            (
                'liquidate with no net rows',
                {
                    'kind': 'liquidate_position',
                },
                {
                    'day': [],
                },
                0,
            ),
            (
                'absolute quantity of zero',
                {
                    'kind': 'absolute',
                },
                None,
                0,
            ),
        ]

    def run(self):
        """Prints each attempt's refusal.

        Returns:
            None: This method returns nothing.
        """
        for description, reference, positions, requested in self.attempts:
            try:
                self.resolver.resolve(reference, positions, RELIANCE, 'SELL', requested)
            except RefusedRequestError as error:
                print(f'{description}: refused with {error.status}: {error.body}')


if __name__ == '__main__':
    NothingToCloseExample().run()
