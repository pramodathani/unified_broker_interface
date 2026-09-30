"""Builds Fyers' place, cancel and modify requests for its v3 API, and checks a stored order's exchange, without sending anything.

Fyers takes orders as JSON on one URL, `/api/v3/orders/sync`, and tells place, modify and cancel apart by the method: POST, PATCH and DELETE. Order types and sides are numbers, so LIMIT is 1 and BUY is 1, SELL is -1. The exchange is part of Fyers' own symbol, such as `NSE:NIFTY26OCT25000CE`, so no market code is sent. A modification sends the order type every time, the prices the new order type takes, and a quantity only when the caller changed it; the modify route puts the caller's new quantity into the modification with `with_quantities`, as the program does.

Fyers' order scripts store the bare exchange, such as `NSE`, on an order, not a market code, so `stored_exchange_matches` compares the instrument's exchange instead; the modify route uses it to check that a stored order is for the instrument it thinks. The option and its handle are made-up values in the shapes `test_runs/order_routes.py` builds, and so are the login and settings.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/fyers/FyersOrders/example_1_building_fyers_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.fyers import FyersOrders
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


class BuildingFyersRequestsExample:
    """Builds one of each Fyers request for a NIFTY option and prints it.

    Attributes:
        broker_orders (FyersOrders): Fyers' order class.
        login (dict): Fyers' decoded login.
        settings (dict): Fyers' decoded settings.
        instrument (Instrument): A NIFTY call option on the NSE.
        handle (dict): Fyers' order handle for the option.
    """

    def __init__(self):
        """Builds the order class, the login, the settings and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = FyersOrders()
        self.login = {
            'access_token': 'example-fyers-token',
        }
        self.settings = {
            'app_id': 'EXAMPLE-100',
        }
        self.handle = {
            'broker_token': '43210',
            'order_symbol': 'NSE:NIFTY26OCT25000CE',
            'lot_size': 75.0,
            'tick_size': 0.05,
        }
        self.instrument = Instrument(
            '11111111-1111-5111-8111-000000000002',
            {
                'segment': 'nse_equity_index_options',
            },
            {
                'fyers': self.handle,
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
        """Builds and prints a place, a cancel and a modification, then checks stored exchanges.

        Returns:
            None: This method returns nothing.
        """
        print(f'Session headers: {self.broker_orders.headers(self.login, self.settings)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'SELL',
            'product': 'NRML',
            'order_type': 'LIMIT',
            'price': '120.05',
            'quantity': 75,
            'tag': 'hedge01',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, self.settings)
        self.show('Place', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE',
                'transaction_type': 'SELL',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'quantity': 75,
                'price': 120.05,
            },
            'data': {},
        })
        cancel_request = self.broker_orders.build_cancel_request('26091500000013', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '26091500000013',
                'quantity': 150,
                'price': '121',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'fyers',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('26091500000013', stored_order, modification.with_quantities(150, 0), self.login, self.settings)
        self.show('Modify the quantity and price', modify_broker_request)
        stored_exchanges = [
            'NSE',
            'nse',
            'BSE',
            None,
        ]
        for stored_exchange in stored_exchanges:
            print(f'Stored exchange {stored_exchange!r} matches the NSE option: {self.broker_orders.stored_exchange_matches(self.instrument, stored_exchange)}')


if __name__ == '__main__':
    BuildingFyersRequestsExample().run()
