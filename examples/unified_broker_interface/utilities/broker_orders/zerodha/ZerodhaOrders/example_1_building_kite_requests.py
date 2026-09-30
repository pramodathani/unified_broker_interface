"""Builds Zerodha's place, cancel and modify requests for Kite Connect and prints what a dry run would show, without sending anything.

Kite takes orders as forms under `/orders/{variety}`, where the variety is `amo` for an after-market order and `regular` otherwise. A MARKET or SL-M order carries `market_protection` of -1, Kite's automatic protection, which Kite has required through its API since April 2026. A cancel and a modification name the variety Kite stored on the order, which the program reads from the stored order's broker fields. Kite changes only the fields a modification sends, so only the order type, the prices the new order type takes, and the fields the caller changed are sent.

The stored stop-loss order is the `MODSTOPLOSS` case from `test_runs/order_routes.py`, and the login and settings are made-up values. `headers` builds the session headers, which a dry run never shows because they carry the credentials.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/zerodha/ZerodhaOrders/example_1_building_kite_requests.py
"""

import json

import werkzeug.datastructures

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
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)


class BuildingKiteRequestsExample:
    """Builds one of each Kite request and prints it.

    Attributes:
        broker_orders (ZerodhaOrders): Zerodha's order class.
        login (dict): Zerodha's decoded login.
        settings (dict): Zerodha's decoded settings.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Zerodha's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login, the settings and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ZerodhaOrders()
        self.login = {
            'access_token': 'example-zerodha-token',
        }
        self.settings = {
            'api_key': 'example-api-key',
        }
        self.handle = {
            'broker_token': '738561',
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
                'zerodha': self.handle,
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
        """Builds and prints an after-market place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        print(f'Session headers: {self.broker_orders.headers(self.login, self.settings)}')
        after_market_order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'CNC',
            'order_type': 'MARKET',
            'quantity': 5,
            'after_market': True,
            'tag': 'longterm01',
        })
        place_request = self.broker_orders.build_place_request(after_market_order, self.instrument, self.handle, self.login, self.settings)
        self.show('After-market place', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'TRIGGER PENDING',
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'SL',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2490.0,
                'trigger_price': 2495.0,
            },
            'data': {
                'variety': 'regular',
            },
        })
        cancel_request = self.broker_orders.build_cancel_request('MODSTOPLOSS', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'MODSTOPLOSS',
                'order_type': 'SL-M',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('MODSTOPLOSS', stored_order, modification, self.login, self.settings)
        self.show('Modify SL to SL-M', modify_broker_request)


if __name__ == '__main__':
    BuildingKiteRequestsExample().run()
