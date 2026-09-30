"""Prepares a Zerodha market order for RELIANCE and answers a dry run from it, without sending anything.

A `PreparedPlacement` is the step between choosing a broker and sending the order. It holds the chosen broker's order class, the request built for it, the brokers passed over on the way, and the identifier and quantity the request carries. A dry run answers from it, and the order engine writes it down before the request leaves.

The program validates the order, decodes the instrument from text, builds Zerodha's request with `ZerodhaOrders.build_place_request` and wraps it. The login and settings are made-up values, and nothing is sent: the dry-run answer is printed instead, in the shape recorded in `test_runs/fixtures/order_routes.jsonl`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_placement/PreparedPlacement/example_1_zerodha_equity_dry_run.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_placement import (
    PreparedPlacement,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)


class ZerodhaEquityDryRunExample:
    """Prepares one order at Zerodha and prints the dry-run answer.

    Attributes:
        prepared (PreparedPlacement): The prepared order.
    """

    def __init__(self):
        """Validates the order, builds Zerodha's request and prepares the placement.

        Returns:
            None: This method returns nothing.
        """
        order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
            'dry_run': True,
        })
        handle = {
            'broker_token': '738561',
            'order_symbol': 'RELIANCE',
            'lot_size': 1.0,
            'tick_size': 0.1,
        }
        instrument = Instrument(
            order.instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': handle,
            },
        )
        login = {
            'access_token': 'example-access-token',
        }
        settings = {
            'api_key': 'example-api-key',
        }
        broker_orders = ZerodhaOrders()
        broker_request = broker_orders.build_place_request(order, instrument, handle, login, settings)
        self.prepared = PreparedPlacement(
            order.instrument_id,
            broker_orders,
            broker_request,
            [],
            identifier_sent=handle['order_symbol'],
            broker_quantity=order.quantity,
        )

    def run(self):
        """Prints the dry-run answer built from the prepared order.

        Returns:
            None: This method returns nothing.
        """
        answer = {
            'broker': self.prepared.broker_name,
            'dry_run': True,
            'instrument_id': self.prepared.instrument_id,
            'request': self.prepared.broker_request.shown(),
            'skipped': self.prepared.skipped,
        }
        print(json.dumps(answer, indent=2, sort_keys=True))
        print(f'Identifier sent: {self.prepared.identifier_sent}, quantity sent: {self.prepared.broker_quantity}')


if __name__ == '__main__':
    ZerodhaEquityDryRunExample().run()
