"""Shows the cases in which `ClosingPositions` refuses to call an order an exit, so the order is priced as an opening one.

Treating an opening order as an exit would send it to a broker without checking its margin, which is the dangerous direction. So the positions document is believed only while it is at most five seconds old and only for brokers whose positions are `ok`, and an order counts as an exit only when it closes no more than the broker holds, in the same product. This program asks the same question in each of those cases with scripted documents, so it needs nothing running.

Notice that only the first line is True. Every other case falls back to the ordinary margin estimate.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/closing_positions/ClosingPositions/example_2_when_the_positions_are_not_trusted.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_selection.utilities.closing_positions import (
    ClosingPositions,
)
from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)

CALL_ID = 'nifty-2026-10-27-22600-ce'


class StandInOrder:
    """An order carrying only what `ClosingPositions` reads.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): `CNC`, `MIS` or `NRML`.
        quantity (int): The quantity in units.
    """

    def __init__(self, transaction_type, product, quantity):
        """Builds the order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            quantity (int): The quantity in units.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.product = product
        self.quantity = quantity


class WhenThePositionsAreNotTrustedExample:
    """Asks whether a sell closes Flattrade's 65 calls under several documents and orders.

    Attributes:
        closing_positions (ClosingPositions): The reader, trusting a document up to five seconds old.
        now (datetime.datetime): The moment the documents are judged at.
    """

    def __init__(self):
        """Builds the reader.

        Returns:
            None: This method returns nothing.
        """
        self.closing_positions = ClosingPositions(5)
        self.now = datetime.datetime(2026, 10, 7, 11, 41, 24)

    def positions_document(self, written_at, flattrade_status):
        """A positions document in which Flattrade holds 65 of the call as a carry position.

        Args:
            written_at (str): The document's `as_of`.
            flattrade_status (str): Flattrade's status in the document.

        Returns:
            str: The document as JSON.
        """
        return json.dumps({
            'net': [
                {
                    'instrument_id': CALL_ID,
                    'product': 'carry',
                    'quantity': 65.0,
                    'by_broker': {
                        'flattrade': 65.0,
                    },
                },
            ],
            'brokers': [
                {
                    'broker': 'flattrade',
                    'status': flattrade_status,
                },
            ],
            'as_of': written_at,
        })

    def answer(self, positions_text, legs):
        """Whether the legs only close a position at Flattrade.

        Args:
            positions_text (str): The positions document.
            legs (OrderLegs): The order's legs.

        Returns:
            bool: The answer.
        """
        holdings = self.closing_positions.holdings(positions_text, self.now)
        return self.closing_positions.closes_only(holdings, legs, 'flattrade')

    def run(self):
        """Prints the answer for each case.

        Returns:
            None: This method returns nothing.
        """
        fresh = self.positions_document('2026-10-07T11:41:23', 'ok')
        sell_65 = OrderLegs([
            (CALL_ID, StandInOrder('SELL', 'NRML', 65)),
        ])
        cases = [
            ('a fresh document, a sell of 65', fresh, sell_65),
            ('a document ten seconds old', self.positions_document('2026-10-07T11:41:14', 'ok'), sell_65),
            ("Flattrade's positions are stale", self.positions_document('2026-10-07T11:41:23', 'stale'), sell_65),
            (
                'a sell of 130, more than is held',
                fresh,
                OrderLegs([
                    (CALL_ID, StandInOrder('SELL', 'NRML', 130)),
                ]),
            ),
            (
                'an intraday sell of a carry position',
                fresh,
                OrderLegs([
                    (CALL_ID, StandInOrder('SELL', 'MIS', 65)),
                ]),
            ),
            (
                'a buy, which adds to the position',
                fresh,
                OrderLegs([
                    (CALL_ID, StandInOrder('BUY', 'NRML', 65)),
                ]),
            ),
        ]
        for name, positions_text, legs in cases:
            print(f'{name}: {self.answer(positions_text, legs)}')


if __name__ == '__main__':
    WhenThePositionsAreNotTrustedExample().run()
