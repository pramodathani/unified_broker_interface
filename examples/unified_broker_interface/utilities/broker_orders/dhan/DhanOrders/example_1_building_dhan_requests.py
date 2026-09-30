"""Builds Dhan's place, cancel and modify requests for its v2 API and prints what a dry run would show, without sending anything.

Dhan takes orders as JSON and names the instrument by its security id, which is the handle's `broker_token`. Products and order types are spelt Dhan's way: MIS is `INTRADAY` and SL is `STOP_LOSS`. An after-market order carries `afterMarketOrder` and `amoTime`, and a caller's tag travels as `correlationId`. A modification restates the whole order after the change, because Dhan requires the order type and validity every time and reads the quantity as the total.

The stored order is the open LIMIT order `test_runs/order_routes.py` stores, and the login and settings are made-up values. `headers` builds the session header, which a dry run never shows.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/dhan/DhanOrders/example_1_building_dhan_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrders
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


class BuildingDhanRequestsExample:
    """Builds one of each Dhan request and prints it.

    Attributes:
        broker_orders (DhanOrders): Dhan's order class.
        login (dict): Dhan's decoded login.
        settings (dict): Dhan's decoded settings.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Dhan's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login, the settings and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = DhanOrders()
        self.login = {
            'access_token': 'example-dhan-token',
        }
        self.settings = {
            'client_id': '1000000001',
        }
        self.handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE',
            'lot_size': 1.0,
            'tick_size': 0.1,
        }
        self.instrument = Instrument(
            '11111111-1111-5111-8111-000000000001',
            {
                'segment': 'nse_equities',
            },
            {
                'dhan': self.handle,
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
        """Builds and prints an after-market stop-loss place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        print(f'Session headers: {self.broker_orders.headers(self.login)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'SL',
            'price': '2480',
            'trigger_price': '2485',
            'quantity': 10,
            'after_market': True,
            'tag': 'stop01',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, self.settings)
        self.show('After-market stop-loss place', place_request)
        print(f'Tag the request carries: {place_request.tag}')
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE_EQ',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'disclosed_quantity': 0,
                'price': 2500.0,
            },
            'data': {},
        })
        cancel_request = self.broker_orders.build_cancel_request('112509150000012', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '112509150000012',
                'price': '2502.5',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'dhan',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('112509150000012', stored_order, modification, self.login, self.settings)
        self.show('Modify the price', modify_broker_request)


if __name__ == '__main__':
    BuildingDhanRequestsExample().run()
