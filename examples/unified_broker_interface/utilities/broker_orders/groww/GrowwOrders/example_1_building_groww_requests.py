"""Builds Groww's place, cancel and modify requests and prints what a dry run would show, without sending anything.

Groww takes orders as JSON and needs a unique `order_reference_id` on each, so the place request generates one from the caller's tag and twelve random hex digits, and answers with it as the order's tag. Those digits change on every run, so the program prints the reference with them replaced by `<random>`. A cancel and a modification name the segment Groww stored on the order; when a websocket update has stored the order without one, the request cannot be built and `OrderNotReadyError` is raised instead.

Groww's order scripts store the bare exchange on an order, so `stored_exchange_matches` compares the instrument's exchange rather than a market code. The login and the stored order are made-up values in the shapes `test_runs/order_routes.py` stores.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/groww/GrowwOrders/example_1_building_groww_requests.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.groww import GrowwOrders
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


class BuildingGrowwRequestsExample:
    """Builds one of each Groww request and prints it.

    Attributes:
        broker_orders (GrowwOrders): Groww's order class.
        login (dict): Groww's decoded login.
        instrument (Instrument): RELIANCE on the NSE.
        handle (dict): Groww's order handle for RELIANCE.
    """

    def __init__(self):
        """Builds the order class, the login and the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = GrowwOrders()
        self.login = {
            'access_token': 'example-groww-token',
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
                'groww': self.handle,
            },
        )

    def show(self, label, shown_request):
        """Prints what a dry run shows of one request.

        Args:
            label (str): Which request it is.
            shown_request (dict): The request as `BrokerRequest.shown` gives it.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}:')
        print(json.dumps(shown_request, indent=2, sort_keys=True))

    def run(self):
        """Builds and prints a place, a cancel and a modification, then shows the refusals and exchange checks.

        Returns:
            None: This method returns nothing.
        """
        print(f'Session headers: {self.broker_orders.headers(self.login)}')
        order = PlaceOrderRequest({
            'instrument_id': self.instrument.instrument_id,
            'transaction_type': 'BUY',
            'product': 'CNC',
            'order_type': 'SL-M',
            'trigger_price': '2520',
            'quantity': 4,
            'tag': 'breakout',
        })
        place_request = self.broker_orders.build_place_request(order, self.instrument, self.handle, self.login, {})
        reference_start = place_request.tag.split('-')[0]
        shown_place = place_request.shown()
        shown_place['json']['order_reference_id'] = f'{reference_start}-<random>'
        self.show('Place', shown_place)
        print(f'Tag answered to the caller: {reference_start}-<random>, {len(place_request.tag)} characters')
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'exchange': 'NSE',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'segment': 'CASH',
            },
        })
        cancel_request = self.broker_orders.build_cancel_request('GMK39038RDVL', stored_order, self.login, {})
        self.show('Cancel', cancel_request.shown())
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'GMK39038RDVL',
                'order_type': 'MARKET',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'groww',
            ],
        )
        modification = OrderModification(modify_request, stored_order)
        modify_broker_request = self.broker_orders.build_modify_request('GMK39038RDVL', stored_order, modification, self.login, {})
        self.show('Modify LIMIT to MARKET', modify_broker_request.shown())
        websocket_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {},
        })
        try:
            self.broker_orders.build_cancel_request('GMKNOSEGMENT', websocket_order, self.login, {})
        except OrderNotReadyError as error:
            print(f'Cancel with no stored segment: HTTP 503, {error}')
        print(f'Stored exchange NSE matches: {self.broker_orders.stored_exchange_matches(self.instrument, "NSE")}')
        print(f'Stored exchange BSE matches: {self.broker_orders.stored_exchange_matches(self.instrument, "BSE")}')


if __name__ == '__main__':
    BuildingGrowwRequestsExample().run()
