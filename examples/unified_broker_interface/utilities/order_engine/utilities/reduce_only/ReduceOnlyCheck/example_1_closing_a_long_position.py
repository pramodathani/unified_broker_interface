"""Checks reduce-only sell orders against a long intraday position of 75 shares.

A reduce-only order is an exit that must never turn into an entry. The engine asks `is_asked_for` whether the caller set `reduce_only`, then, just before sending each leg, calls `refuse_if_it_adds`, which reads the net position with `held` and raises `RefusedRequestError` when the leg is on the wrong side or bigger than the position.

The check reads positions through the engine's placement object, whose `market_context` returns the unified positions document. A small stand-in replaces that placement and returns a fixed document holding 75 shares long on MIS (intraday) and 20 shares long on CNC (delivery) in the same instrument, so the program also shows that only the order's own product counts. The orders are real `PlaceOrderRequest` objects built from request bodies.

Notice that a sell of 50 passes silently, a sell of 100 is refused because it would leave the account 25 short, and a buy is refused because it would add to the long.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/reduce_only/ReduceOnlyCheck/example_1_closing_a_long_position.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    ReduceOnlyCheck,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class PositionsPlacement:
    """A stand-in for the engine's placement that answers with one fixed positions document.

    Attributes:
        positions (dict): The unified positions document.
    """

    def __init__(self, positions):
        """Builds the stand-in.

        Args:
            positions (dict): The unified positions document to answer with.

        Returns:
            None: This method returns nothing.
        """
        self.positions = positions

    def market_context(self, instrument_id, want_quote, want_positions):
        """Returns the positions document the way the real placement does.

        Args:
            instrument_id (str): The instrument, which is ignored.
            want_quote (bool): Whether a quote was asked for, which is ignored.
            want_positions (bool): Whether positions were asked for, which is ignored.

        Returns:
            tuple: No instrument, no quote and the positions document.
        """
        return None, None, self.positions


class ClosingALongPositionExample:
    """Runs three orders through the reduce-only check against a long position.

    Attributes:
        check (ReduceOnlyCheck): The check being shown.
        bodies (list): The request bodies to check.
    """

    def __init__(self):
        """Builds the check over a long MIS position of 75 and a long CNC position of 20.

        Returns:
            None: This method returns nothing.
        """
        positions = {
            'net': [
                {
                    'instrument_id': INSTRUMENT_ID,
                    'product': 'intraday',
                    'quantity': 75,
                },
                {
                    'instrument_id': INSTRUMENT_ID,
                    'product': 'delivery',
                    'quantity': 20,
                },
            ],
            'day': [],
        }
        self.check = ReduceOnlyCheck(PositionsPlacement(positions))
        self.bodies = [
            self.body('SELL', 50),
            self.body('SELL', 100),
            self.body('BUY', 10),
        ]

    def body(self, transaction_type, quantity):
        """Builds one intraday market order body for the instrument.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            quantity (int): The quantity.

        Returns:
            dict: The request body.
        """
        return {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': transaction_type,
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': quantity,
        }

    def run(self):
        """Prints the positions held and the answer for each order.

        Returns:
            None: This method returns nothing.
        """
        parameters = {
            'type': 'simple',
            'reduce_only': True,
        }
        print(f'Reduce-only asked for: {self.check.is_asked_for(parameters)}')
        print(f'Held on MIS: {self.check.held(INSTRUMENT_ID, "MIS")}')
        print(f'Held on CNC: {self.check.held(INSTRUMENT_ID, "CNC")}')
        for body in self.bodies:
            order = PlaceOrderRequest(body)
            label = f'{order.transaction_type} {order.quantity}'
            try:
                self.check.refuse_if_it_adds(order, INSTRUMENT_ID)
            except RefusedRequestError as refusal:
                print(f'{label}: refused with {refusal.status}: {refusal.body["error"]}')
                continue
            print(f'{label}: allowed')


if __name__ == '__main__':
    ClosingALongPositionExample().run()
