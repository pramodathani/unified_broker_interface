"""Decides at which brokers selling 65 NIFTY 22600 calls only closes a position, as on 2026-10-07 when the exit was refused.

On 2026-10-07 a program bought 65 of the NIFTY 27 Oct 22600 call through Flattrade and two seconds later sent a sell to close them. The funds check priced that sell as writing a new call, about two lakh of margin, which no account held, so every broker was passed over and the sell was refused with `no broker can take this order`. `ClosingPositions` reads each broker's share of every position from the unified positions document, and says the sell only closes what Flattrade holds, so the funds check no longer passes Flattrade over. This program uses a scripted positions document, so it needs nothing running.

Notice that only Flattrade is answered True. Zerodha holds nothing in this call, so at Zerodha the same sell would open a short and is priced as before.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/closing_positions/ClosingPositions/example_1_an_exit_from_a_bought_call.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_selection.utilities.closing_positions import (
    ClosingPositions,
)
from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)

CALL_ID = '4ac42975-514c-5b34-8b8a-1ef14fdde055'


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


class AnExitFromABoughtCallExample:
    """Asks, for two brokers, whether the sell only closes a position there.

    Attributes:
        closing_positions (ClosingPositions): The reader, trusting a document up to five seconds old.
        now (datetime.datetime): The moment the document is judged at.
    """

    def __init__(self):
        """Builds the reader.

        Returns:
            None: This method returns nothing.
        """
        self.closing_positions = ClosingPositions(5)
        self.now = datetime.datetime(2026, 10, 7, 11, 41, 24)

    def positions_document(self):
        """The unified positions document a second before the sell, with Flattrade holding the 65 calls.

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
                    'status': 'ok',
                },
                {
                    'broker': 'zerodha',
                    'status': 'ok',
                },
            ],
            'as_of': '2026-10-07T11:41:23',
        })

    def run(self):
        """Reads the holdings and prints the answer for each broker.

        Returns:
            None: This method returns nothing.
        """
        holdings = self.closing_positions.holdings(self.positions_document(), self.now)
        for (instrument_id, product), by_broker in holdings.items():
            print(f'{instrument_id} {product}: {by_broker}')
        legs = OrderLegs([
            (CALL_ID, StandInOrder('SELL', 'NRML', 65)),
        ])
        for broker_name in ['flattrade', 'zerodha']:
            closes = self.closing_positions.closes_only(holdings, legs, broker_name)
            print(f'Selling 65 at {broker_name} only closes a position: {closes}')


if __name__ == '__main__':
    AnExitFromABoughtCallExample().run()
