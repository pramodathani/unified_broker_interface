"""Builds Flattrade's place, cancel and modify requests for its PiConnect API and prints what a dry run would show, without sending anything.

Flattrade runs the Noren platform, so `FlattradeOrders` inherits every request builder from `NorenOrders` and only names its base URL, `https://piconnect.flattrade.in/PiConnectAPI`, and the setting that holds its account id, `username`. The body is a form field `jData` holding the order as JSON, followed by `jKey`, the session token; a dry run shows the readable fields instead of that encoded body.

The place request below is for a crude oil future, which Flattrade counts in its own lot size, so the caller's 200 barrels become 2 once `order_quantities` converts them with the morning's trusted contract size of 100 barrels a lot. The stored order is the shape `test_runs/order_routes.py` stores, and the login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/flattrade/FlattradeOrders/example_1_building_flattrade_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.flattrade import (
    FlattradeOrders,
)
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


class BuildingFlattradeRequestsExample:
    """Builds one of each Flattrade request and prints it.

    Attributes:
        broker_orders (FlattradeOrders): Flattrade's order class.
        login (dict): Flattrade's decoded login.
        settings (dict): Flattrade's decoded settings.
    """

    def __init__(self):
        """Builds the order class, the login and the settings.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = FlattradeOrders()
        self.login = {
            'access_token': 'example-flattrade-token',
        }
        self.settings = {
            'username': 'FT000001',
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
        """Builds and prints a crude oil place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '569900',
            'order_symbol': 'CRUDEOIL19OCT26',
            'lot_size': 1.0,
            'tick_size': 1.0,
        }
        crude = Instrument(
            '22222222-2222-5222-8222-000000000001',
            {
                'segment': 'mcx_commodity_futures',
            },
            {
                'flattrade': handle,
            },
            {
                'units_per_lot': '100',
                'status': 'confirmed',
                'tradeable': True,
            },
        )
        order = PlaceOrderRequest({
            'instrument_id': crude.instrument_id,
            'transaction_type': 'BUY',
            'product': 'NRML',
            'order_type': 'LIMIT',
            'price': '6000',
            'quantity': 200,
        })
        quantity, disclosed_quantity = self.broker_orders.order_quantities(order, crude, handle)
        broker_order = order.with_quantities(quantity, disclosed_quantity)
        place_request = self.broker_orders.build_place_request(broker_order, crude, handle, self.login, self.settings)
        self.show('Crude oil place', place_request)
        print(f'Encoded body starts: {place_request.data[:24]}')
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE',
                'tradingsymbol': 'RELIANCE-EQ',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {},
        })
        cancel_request = self.broker_orders.build_cancel_request('26091500000021', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '26091500000021',
                'price': '2501.5',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'flattrade',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('26091500000021', stored_order, modification, self.login, self.settings)
        self.show('Modify the price', modify_broker_request)


if __name__ == '__main__':
    BuildingFlattradeRequestsExample().run()
