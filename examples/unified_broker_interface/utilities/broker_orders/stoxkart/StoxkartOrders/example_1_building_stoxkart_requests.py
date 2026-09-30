"""Builds Stoxkart's place, cancel and modify requests and shows where its Algo-ID and order variety come from, without sending anything.

Stoxkart takes orders as JSON under `/orders/{variety}` and requires an Algo-ID both in the `X-Algo-Id` header and in the body. `algo_identifier` reads it from Stoxkart's settings, where it can be changed without a release, and falls back to `99999` when the settings have none, because Stoxkart once started refusing that value. A cancel and a modification name the order's variety, which `order_variety` reads from the value the order scripts stored beside the order, then from the order's own fields, then falls back to `normal`.

The stored orders are the shapes `test_runs/order_routes.py` stores, including the after-market one whose variety is kept beside the order; the modify route puts the caller's new disclosed quantity into the modification with `with_quantities`, as the program does. The login and settings are made-up values. `headers` builds the session headers, which a dry run never shows.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/stoxkart/StoxkartOrders/example_1_building_stoxkart_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.stoxkart import (
    StoxkartOrders,
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


class BuildingStoxkartRequestsExample:
    """Builds one of each Stoxkart request and prints it.

    Attributes:
        broker_orders (StoxkartOrders): Stoxkart's order class.
        login (dict): Stoxkart's decoded login.
        settings (dict): Stoxkart's decoded settings, with an Algo-ID of their own.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Stoxkart's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login, the settings and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = StoxkartOrders()
        self.login = {
            'access_token': 'example-stoxkart-token',
        }
        self.settings = {
            'ucc_code': 'SX00001',
            'api_key': 'example-api-key',
            'algo_id': ' 12345 ',
        }
        self.handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE-EQ',
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        self.instrument = Instrument(
            '11111111-1111-5111-8111-000000000001',
            {
                'segment': 'nse_equities',
            },
            {
                'stoxkart': self.handle,
            },
        )

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
        """Shows the Algo-ID and varieties, then builds a place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        print(f'Algo-ID from the settings: {self.broker_orders.algo_identifier(self.settings)!r}')
        print(f'Algo-ID when the settings have none: {self.broker_orders.algo_identifier({})!r}')
        print(f'Session headers: {self.broker_orders.headers(self.login, self.settings)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'SELL',
            'product': 'CNC',
            'order_type': 'SL',
            'price': '2450',
            'trigger_price': '2455',
            'quantity': 2,
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, self.settings)
        self.show('Stop-loss place', place_request)
        after_market_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE',
                'instrument_token': '2885',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'variety': 'NORMAL',
            },
            'variety': 'AMO',
        })
        bracket_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {
                'variety': 'BO',
            },
        })
        plain_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {},
        })
        print(f'Variety kept beside the order: {self.broker_orders.order_variety(after_market_order)}')
        print(f'Variety in the order itself: {self.broker_orders.order_variety(bracket_order)}')
        print(f'Variety when none is stored: {self.broker_orders.order_variety(plain_order)}')
        cancel_request = self.broker_orders.build_cancel_request('SX0001', after_market_order, self.login, self.settings)
        self.show('Cancel the after-market order', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'SX0001',
                'price': '2505',
                'disclosed_quantity': 5,
            },
            werkzeug.datastructures.MultiDict(),
            [
                'stoxkart',
            ],
        )
        modification = OrderModification(modify_request, after_market_order)
        modify_broker_request = self.broker_orders.build_modify_request('SX0001', after_market_order, modification.with_quantities(10, 5), self.login, self.settings)
        self.show('Modify the price and disclosed quantity', modify_broker_request)


if __name__ == '__main__':
    BuildingStoxkartRequestsExample().run()
