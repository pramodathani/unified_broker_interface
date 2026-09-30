"""Shows the reduce-only check refusing an order when nothing is held, accepting a buy-back of a short, and rejecting a malformed flag.

`is_asked_for` treats a missing `reduce_only` or `false` as "not reduce-only", `true` as "reduce-only", and anything else, such as the string `"yes"`, as a caller mistake answered with HTTP 400.

The program then checks two orders with the flag set. A small stand-in placement answers with a positions document holding a short of 40 in one instrument and nothing in another. A buy of 40 closes the short exactly and passes. A sell in the instrument with no position is refused with HTTP 409, because a reduce-only order can never open a position. The orders are real `PlaceOrderRequest` objects.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/reduce_only/ReduceOnlyCheck/example_2_nothing_held_or_bad_flag.py
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

SHORT_INSTRUMENT_ID = '11111111-1111-5111-8111-000000000004'
FLAT_INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


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


class NothingHeldOrBadFlagExample:
    """Reads three flag values, then checks a buy-back and an order with nothing held.

    Attributes:
        check (ReduceOnlyCheck): The check being shown.
    """

    def __init__(self):
        """Builds the check over a short carried position of 40.

        Returns:
            None: This method returns nothing.
        """
        positions = {
            'net': [
                {
                    'instrument_id': SHORT_INSTRUMENT_ID,
                    'product': 'carry',
                    'quantity': -40,
                },
            ],
            'day': [],
        }
        self.check = ReduceOnlyCheck(PositionsPlacement(positions))

    def run(self):
        """Prints the flag readings and the answers for two orders.

        Returns:
            None: This method returns nothing.
        """
        flag_values = [
            {},
            {
                'reduce_only': False,
            },
            {
                'reduce_only': 'yes',
            },
        ]
        for parameters in flag_values:
            try:
                answer = self.check.is_asked_for(parameters)
            except RefusedRequestError as refusal:
                print(f'{parameters}: refused with {refusal.status}: {refusal.body["error"]}')
                continue
            print(f'{parameters}: {answer}')
        print(f'Held in the short instrument on NRML: {self.check.held(SHORT_INSTRUMENT_ID, "NRML")}')
        buy_back = PlaceOrderRequest({
            'instrument_id': SHORT_INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'NRML',
            'order_type': 'MARKET',
            'quantity': 40,
        })
        self.check.refuse_if_it_adds(buy_back, SHORT_INSTRUMENT_ID)
        print('BUY 40 against the short of 40: allowed')
        opening_sell = PlaceOrderRequest({
            'instrument_id': FLAT_INSTRUMENT_ID,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 5,
        })
        try:
            self.check.refuse_if_it_adds(opening_sell, FLAT_INSTRUMENT_ID)
        except RefusedRequestError as refusal:
            print(f'SELL 5 with nothing held: refused with {refusal.status}')
            print(f'  Body: {refusal.body}')


if __name__ == '__main__':
    NothingHeldOrBadFlagExample().run()
