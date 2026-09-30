"""Builds Wisdom Capital's place, cancel and modify requests for its XTS server, and runs the checks peculiar to it, without sending anything.

XTS takes the instrument as a number, so `handle_skip_reason` passes Wisdom Capital over when the mapping's instrument id is not all digits. Its orders carry an `orderUniqueIdentifier`, which is the caller's tag or `ubi`; a cancel and a modification must repeat the one stored on the order, which `unique_identifier` reads. XTS also takes the application order id as an integer when it is all digits, which `application_order_id` decides. Wisdom Capital's certificate does not match its host, so every request is built with certificate checking off.

A cancel carries its fields in the query string, and a modification restates every field XTS requires. The stored order is the shape `test_runs/order_routes.py` stores, and the login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/wisdom_capital/WisdomCapitalOrders/example_1_building_xts_requests.py
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
from unified_broker_interface.utilities.broker_orders.wisdom_capital import (
    WisdomCapitalOrders,
)


class BuildingXtsRequestsExample:
    """Builds one of each XTS request and runs the handle and identifier checks.

    Attributes:
        broker_orders (WisdomCapitalOrders): Wisdom Capital's order class.
        login (dict): Wisdom Capital's decoded login.
        settings (dict): Wisdom Capital's decoded settings.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Wisdom Capital's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login, the settings and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = WisdomCapitalOrders()
        self.login = {
            'access_token': 'example-xts-token',
        }
        self.settings = {
            'ucc_code': 'WC00001',
        }
        self.handle = {
            'broker_token': '2885',
            'order_symbol': None,
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        self.instrument = Instrument(
            '11111111-1111-5111-8111-000000000001',
            {
                'segment': 'nse_equities',
            },
            {
                'wisdom_capital': self.handle,
            },
        )

    def show(self, label, broker_request):
        """Prints what a dry run shows of one request, and whether its certificate is checked.

        Args:
            label (str): Which request it is.
            broker_request (BrokerRequest): The request.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label} (certificate checked: {broker_request.verify_certificate}):')
        print(json.dumps(broker_request.shown(), indent=2, sort_keys=True))

    def run(self):
        """Runs the checks and builds a place, a cancel and a modification.

        Returns:
            None: This method returns nothing.
        """
        text_handle = {
            'broker_token': 'ABC',
        }
        print(f'Handle with instrument id 2885: {self.broker_orders.handle_skip_reason(self.handle)}')
        print(f'Handle with instrument id ABC: {self.broker_orders.handle_skip_reason(text_handle)}')
        print(f'Application order id 1234567890: {self.broker_orders.application_order_id("1234567890")!r}')
        print(f'Application order id W-ABC: {self.broker_orders.application_order_id("W-ABC")!r}')
        print(f'Session headers: {self.broker_orders.headers(self.login)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': '2500',
            'quantity': 10,
            'tag': 'T1',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, self.settings)
        self.show('Place', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'OrderUniqueIdentifier': 'T1',
            },
        })
        untagged_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {},
        })
        print(f'Unique identifier stored on the order: {self.broker_orders.unique_identifier(stored_order)}')
        print(f'Unique identifier when none is stored: {self.broker_orders.unique_identifier(untagged_order)}')
        cancel_request = self.broker_orders.build_cancel_request('1234567890', stored_order, self.login, self.settings)
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': '1234567890',
                'order_type': 'SL',
                'trigger_price': '2495',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'wisdom_capital',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('1234567890', stored_order, modification, self.login, self.settings)
        self.show('Modify LIMIT to SL', modify_broker_request)


if __name__ == '__main__':
    BuildingXtsRequestsExample().run()
