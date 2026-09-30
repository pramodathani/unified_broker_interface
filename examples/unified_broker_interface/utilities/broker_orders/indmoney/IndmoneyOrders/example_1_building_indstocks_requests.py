"""Builds INDmoney's place, cancel and modify requests for the INDstocks API and prints what a dry run would show, without sending anything.

INDmoney takes orders as JSON, names the instrument by its security id, and carries an Algo-ID for the exchange, which differs between the NSE and the BSE. Its cancel and modify requests need the order's segment, `EQUITY` or `DERIVATIVE`; `order_segment` takes the one the order scripts stored, and when there is none guesses it from the order id, since INDmoney's derivative order ids start with `DRV`. A modification can change only the quantity and the limit price, and restates both.

The order ids are the ones `test_runs/order_routes.py` stores, and the login is a made-up value. INDmoney's order scripts store the bare exchange on an order, which `stored_exchange_matches` compares.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/indmoney/IndmoneyOrders/example_1_building_indstocks_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.indmoney import (
    IndmoneyOrders,
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


class BuildingIndstocksRequestsExample:
    """Builds one of each INDmoney request and prints it.

    Attributes:
        broker_orders (IndmoneyOrders): INDmoney's order class.
        login (dict): INDmoney's decoded login.
        instrument (Instrument): RELIANCE on the BSE.
        handle (dict): INDmoney's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = IndmoneyOrders()
        self.login = {
            'access_token': 'example-indmoney-token',
        }
        self.handle = {
            'broker_token': '500325',
            'order_symbol': 'RELIANCE',
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        self.instrument = Instrument(
            '11111111-1111-5111-8111-000000000003',
            {
                'segment': 'bse_equities',
            },
            {
                'indmoney': self.handle,
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
        """Builds and prints a place, a cancel and a modification, then shows segment guesses and exchange checks.

        Returns:
            None: This method returns nothing.
        """
        print(f'Session headers: {self.broker_orders.headers(self.login)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'CNC',
            'order_type': 'LIMIT',
            'price': '2499.95',
            'quantity': 3,
            'tag': 'sip01',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, {})
        self.show('Place on the BSE', place_request)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'quantity': 3,
                'price': 2499.95,
            },
            'data': {},
        })
        cancel_request = self.broker_orders.build_cancel_request('EQ-100072817', stored_order, self.login, {})
        self.show('Cancel', cancel_request)
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'EQ-100072817',
                'price': '2498',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'indmoney',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('EQ-100072817', stored_order, modification, self.login, {})
        self.show('Modify the price', modify_broker_request)
        stored_with_segment = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {
                'segment': 'DERIVATIVE',
            },
        })
        print(f'Segment of EQ-100072817 with none stored: {self.broker_orders.order_segment("EQ-100072817", stored_order)}')
        print(f'Segment of DRV-200000001 with none stored: {self.broker_orders.order_segment("DRV-200000001", stored_order)}')
        print(f'Segment of X-1 with DERIVATIVE stored: {self.broker_orders.order_segment("X-1", stored_with_segment)}')
        print(f'Stored exchange bse matches: {self.broker_orders.stored_exchange_matches(self.instrument, "bse")}')
        print(f'Stored exchange NSE matches: {self.broker_orders.stored_exchange_matches(self.instrument, "NSE")}')


if __name__ == '__main__':
    BuildingIndstocksRequestsExample().run()
