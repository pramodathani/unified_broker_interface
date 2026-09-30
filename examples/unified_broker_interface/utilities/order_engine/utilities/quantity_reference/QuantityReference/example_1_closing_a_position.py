"""Works out the quantity and side that close or reduce a position, from the unified positions document.

A caller can send `quantity_reference` instead of a quantity, such as "liquidate my RELIANCE position". The order engine reads `unified:portfolio:positions` and hands the document to `QuantityReference.resolve`, which answers with a quantity in units and the side that closes it: selling a long, buying a short. This program writes that document by hand, holding a long intraday position and a short delivery position in the same instrument.

Nothing is read from Redis. Notice that liquidating without naming a product nets every product together, that naming one product closes only that row, that a reduce larger than the position is capped at the position, and that an `absolute` reference simply passes the caller's own quantity and side through. The program also calls `position_quantity` and `whole` directly, to show how a row with a quantity written as text or left empty is counted.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/quantity_reference/QuantityReference/example_1_closing_a_position.py
"""

from unified_broker_interface.utilities.order_engine.utilities.quantity_reference import (
    QuantityReference,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'
INFY = '11111111-1111-5111-8111-000000000006'


class ClosingAPositionExample:
    """Resolves several quantity references against one positions document and prints the answers.

    Attributes:
        resolver (QuantityReference): The resolver being shown.
        positions (dict): The unified positions document.
        cases (list): Triples of (reference, side asked for, quantity asked for).
    """

    def __init__(self):
        """Builds the resolver, the positions and the cases.

        Returns:
            None: This method returns nothing.
        """
        self.resolver = QuantityReference()
        self.positions = {
            'net': [
                {
                    'instrument_id': RELIANCE,
                    'product': 'intraday',
                    'quantity': 250,
                },
                {
                    'instrument_id': RELIANCE,
                    'product': 'delivery',
                    'quantity': '-100',
                },
                {
                    'instrument_id': INFY,
                    'product': 'intraday',
                    'quantity': None,
                },
            ],
            'day': [],
        }
        self.cases = [
            (
                {
                    'kind': 'liquidate_position',
                },
                'BUY',
                0,
            ),
            (
                {
                    'kind': 'liquidate_position',
                    'product': 'delivery',
                },
                'SELL',
                0,
            ),
            (
                {
                    'kind': 'reduce_position',
                    'product': 'intraday',
                },
                'BUY',
                100,
            ),
            (
                {
                    'kind': 'reduce_position',
                    'product': 'intraday',
                },
                'BUY',
                1000,
            ),
            (
                {
                    'kind': 'absolute',
                },
                'BUY',
                75,
            ),
        ]

    def run(self):
        """Prints each case's quantity and side, then the helpers' answers.

        Returns:
            None: This method returns nothing.
        """
        for reference, side, requested in self.cases:
            quantity, closing_side = self.resolver.resolve(reference, self.positions, RELIANCE, side, requested)
            print(f'{reference}, asked {side} {requested}: send {closing_side} {quantity}')
        net = self.resolver.position_quantity(self.positions, RELIANCE, None, 'liquidate_position')
        print(f'Net RELIANCE across products: {net}')
        print(f'whole of "-100": {self.resolver.whole("-100")}')
        print(f'whole of None: {self.resolver.whole(None)}')
        print(f'whole of "lots": {self.resolver.whole("lots")}')


if __name__ == '__main__':
    ClosingAPositionExample().run()
