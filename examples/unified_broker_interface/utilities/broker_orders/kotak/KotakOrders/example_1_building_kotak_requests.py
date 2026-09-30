"""Builds Kotak Neo's place, cancel and modify requests and runs the checks Kotak adds to its login, without sending anything.

Kotak's host differs between accounts and logins, so `base_url` reads it from the stored login, adds a scheme when it has none, and falls back to Kotak's default host when the login names none. Kotak also needs a `sid` beside the access token: `login_skip_reason` passes Kotak over for a placement without one, and `cancel_login_problem` refuses a cancel or modification.

Kotak takes the order as a JSON string in a `jData` form field. A cancel of an after-market order must say so, which the cancel request reads from Kotak's own `ordGenTp` field on the stored order. A modification restates the whole order in Kotak's modify keys and reads the trading symbol from Kotak's own `trdSym`. The stored order is the one `test_runs/order_routes.py` stores, and the logins are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/kotak/KotakOrders/example_1_building_kotak_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.kotak import KotakOrders
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


class BuildingKotakRequestsExample:
    """Builds one of each Kotak request and runs the login checks.

    Attributes:
        broker_orders (KotakOrders): Kotak's order class.
        login (dict): Kotak's decoded login, with a host and a sid.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Kotak's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = KotakOrders()
        self.login = {
            'access_token': 'example-kotak-token',
            'sid': 'example-sid',
            'base_url': 'mis.kotaksecurities.com/',
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
                'kotak': self.handle,
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
        """Runs the login checks and builds a place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        no_sid = {
            'access_token': 'example-kotak-token',
        }
        print(f'Base URL from the login: {self.broker_orders.base_url(self.login)}')
        print(f'Base URL when the login names none: {self.broker_orders.base_url(no_sid)}')
        print(f'Place skip reason with a sid: {self.broker_orders.login_skip_reason(self.login)}')
        print(f'Place skip reason without a sid: {self.broker_orders.login_skip_reason(no_sid)}')
        print(f'Cancel problem without a sid: {self.broker_orders.cancel_login_problem(no_sid)}')
        print(f'Session headers: {self.broker_orders.headers(self.login)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': '2500.05',
            'quantity': 10,
            'tag': 'kotak01',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, {})
        self.show('Place', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'instrument_token': '2885',
                'exchange': 'nse_cm',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.05,
            },
            'data': {
                'trdSym': 'RELIANCE-EQ',
                'ordGenTp': 'AMO',
            },
        })
        cancel_request = self.broker_orders.build_cancel_request('260915000204304', stored_order, self.login, {})
        self.show('Cancel an after-market order', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '260915000204304',
                'price': '2499',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'kotak',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('260915000204304', stored_order, modification, self.login, {})
        self.show('Modify the price', modify_broker_request)


if __name__ == '__main__':
    BuildingKotakRequestsExample().run()
