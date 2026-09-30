"""Declares a Noren broker in four lines on top of `NorenOrders`, and builds its place, cancel and modify requests.

Flattrade and Shoonya both run the Noren platform, so their request builders live once in `NorenOrders`. A Noren broker class only names itself, its `BASE_URL`, the setting that holds its account id, and the settings each request needs. The program declares a made-up third Noren broker the same way and builds each request with it, without sending anything.

Every Noren body is `jData=<the order as JSON>&jKey=<session token>`. `encoded_body` escapes `&` inside the JSON, so a symbol such as `M&M-EQ` cannot end the `jData` field early; the program prints that part of the body. A dry run shows the readable fields rather than the encoded body. The stored order is the shape `test_runs/order_routes.py` stores, and the login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/noren/NorenOrders/example_1_declaring_a_noren_broker.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.noren import NorenOrders
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class ExampleNorenOrders(NorenOrders):
    """A made-up broker on the Noren platform."""

    BROKER_NAME = 'example_noren'
    BASE_URL = 'https://api.example-noren.in/NorenWClientTP'
    ACCOUNT_SETTINGS_FIELD = 'client_code'
    PLACE_SETTINGS_FIELDS = [
        'client_code',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'client_code',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'client_code',
    ]


class DeclaringANorenBrokerExample:
    """Builds each request for the made-up Noren broker and prints it.

    Attributes:
        broker_orders (ExampleNorenOrders): The made-up broker's order class.
        login (dict): The decoded login.
        settings (dict): The decoded settings.
    """

    def __init__(self):
        """Builds the order class, the login and the settings.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleNorenOrders()
        self.login = {
            'access_token': 'example-session-token',
        }
        self.settings = {
            'client_code': 'EN00001',
        }

    def show(self, label, broker_request):
        """Prints what a dry run shows of one request.

        Args:
            label (str): Which request it is.
            broker_request (BrokerRequest): The request.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}:')
        print(json.dumps(broker_request.shown(), indent=2, sort_keys=True))

    def run(self):
        """Encodes a body, then builds and prints a place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        noren_fields = {
            'uid': 'EN00001',
            'tsym': 'M&M-EQ',
        }
        print(f'Encoded body: {self.broker_orders.encoded_body(noren_fields, self.login)}')
        handle = {
            'broker_token': '2031',
            'order_symbol': 'M&M-EQ',
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        instrument = Instrument(
            '11111111-1111-5111-8111-000000000004',
            {
                'segment': 'nse_equities',
            },
            {
                'example_noren': handle,
            },
        )
        order = PlaceOrderRequest({
            'instrument_id': instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'SL-M',
            'trigger_price': '3010',
            'quantity': 5,
            'validity': 'IOC',
            'tag': 'mm01',
        })
        place_request = self.broker_orders.build_place_request(order, instrument, handle, self.login, self.settings)
        self.show('Stop-loss place', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE',
                'tradingsymbol': 'M&M-EQ',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 5,
                'price': 3000.0,
            },
            'data': {},
        })
        cancel_request = self.broker_orders.build_cancel_request('26091500000031', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '26091500000031',
                'order_type': 'SL',
                'trigger_price': '2995',
                'disclosed_quantity': 1,
            },
            werkzeug.datastructures.MultiDict(),
            [
                'example_noren',
            ],
        )
        modification = OrderModification(modify_request, stored_order).with_quantities(5, 1)
        modify_broker_request = self.broker_orders.build_modify_request('26091500000031', stored_order, modification, self.login, self.settings)
        self.show('Modify LIMIT to SL with a disclosed quantity', modify_broker_request)


if __name__ == '__main__':
    DeclaringANorenBrokerExample().run()
