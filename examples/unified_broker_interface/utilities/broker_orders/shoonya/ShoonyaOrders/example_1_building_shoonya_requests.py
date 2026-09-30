"""Builds Shoonya's place and modify requests, and shows which modifications Shoonya refuses before anything is built.

Shoonya runs the Noren platform, so `ShoonyaOrders` inherits its request builders from `NorenOrders` and only names its base URL, `https://api.shoonya.com/NorenWClientAPI`, and the setting holding its account id, `ucc_code`. A Noren modification can only leave an order as LIMIT or SL, so the modify route refuses a change to MARKET with `modify_field_problem` rather than sending it. A Noren modification also needs the exchange and trading symbol the order was placed with; an order stored without them raises `OrderNotReadyError`.

The stored orders are the shapes `test_runs/order_routes.py` stores, including the `TRIGGER PENDING` one, and the login and settings are made-up values. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/shoonya/ShoonyaOrders/example_1_building_shoonya_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.shoonya import (
    ShoonyaOrders,
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
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class BuildingShoonyaRequestsExample:
    """Builds a Shoonya place and modification, and shows two refusals.

    Attributes:
        broker_orders (ShoonyaOrders): Shoonya's order class.
        login (dict): Shoonya's decoded login.
        settings (dict): Shoonya's decoded settings.
    """

    def __init__(self):
        """Builds the order class, the login and the settings.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ShoonyaOrders()
        self.login = {
            'access_token': 'example-shoonya-token',
        }
        self.settings = {
            'ucc_code': 'FA00001',
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

    def modify_request(self, body):
        """Validates a modification body.

        Args:
            body (dict): The body.

        Returns:
            ModifyOrderRequest: The validated modification.
        """
        return ModifyOrderRequest(
            body,
            werkzeug.datastructures.MultiDict(),
            [
                'shoonya',
            ],
        )

    def run(self):
        """Builds a place and a modification, then shows the two refusals.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '2885',
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
                'shoonya': handle,
            },
        )
        order = PlaceOrderRequest({
            'instrument_id': instrument.instrument_id,
            'transaction_type': 'SELL',
            'product': 'CNC',
            'order_type': 'MARKET',
            'quantity': 7,
            'after_market': True,
        })
        place_request = self.broker_orders.build_place_request(order, instrument, handle, self.login, self.settings)
        self.show('After-market place for M&M', place_request)
        stop_loss_order = StoredOrder({
            'order': {
                'status': 'TRIGGER PENDING',
                'exchange': 'NSE',
                'tradingsymbol': 'RELIANCE-EQ',
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'SL',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2490.0,
                'trigger_price': 2495.0,
            },
            'data': {},
        })
        lower_trigger = self.modify_request({
            'order_id': '26091500099999',
            'trigger_price': '2493',
            'price': '2488',
        })
        print(f'Field problem for a new trigger: {self.broker_orders.modify_field_problem(lower_trigger)}')
        modification = OrderModification(lower_trigger, stop_loss_order)
        modify_broker_request = self.broker_orders.build_modify_request('26091500099999', stop_loss_order, modification, self.login, self.settings)
        self.show('Modify the stop-loss prices', modify_broker_request)
        to_market = self.modify_request({
            'order_id': '26091500099999',
            'order_type': 'MARKET',
        })
        print(f'Field problem for a change to MARKET: {self.broker_orders.modify_field_problem(to_market)}')
        websocket_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {},
        })
        new_price = self.modify_request({
            'order_id': '26091500000022',
            'price': '2501',
        })
        try:
            self.broker_orders.build_modify_request('26091500000022', websocket_order, OrderModification(new_price, websocket_order), self.login, self.settings)
        except OrderNotReadyError as error:
            print(f'Modify with no stored exchange: HTTP 503, {error}')


if __name__ == '__main__':
    BuildingShoonyaRequestsExample().run()
