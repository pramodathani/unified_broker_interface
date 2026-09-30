"""Catches the `OrderNotReadyError` Dhan's modify request raises when Redis does not yet hold the order's validity.

Dhan requires the validity on every modification. When a caller changes only the price of an order whose validity the order scripts have not stored yet, `DhanOrders.build_modify_request` cannot fill that field, and it raises `OrderNotReadyError` rather than guessing. The route answers that with HTTP 503 and the error's message, which tells the caller to try again after the next order book poll.

The request is only built, never sent, and the login and settings are made-up values. The stored order is the open LIMIT order `test_runs/order_routes.py` stores, without its `validity`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/stored_order/OrderNotReadyError/example_1_dhan_modify_without_validity.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrders
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class DhanModifyWithoutValidityExample:
    """Tries to build a Dhan modification for an order whose validity is unknown.

    Attributes:
        broker_orders (DhanOrders): Dhan's order class.
        modification (OrderModification): The stored order with the new price laid over it.
    """

    def __init__(self):
        """Builds the modification from a stored order that lacks its validity.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = DhanOrders()
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'order_id': '1120250930000001',
                'exchange': 'NSE_EQ',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'disclosed_quantity': 0,
                'price': 2500.0,
                'trigger_price': 0.0,
            },
            'data': {},
        })
        modify_request = ModifyOrderRequest(
            {
                'order_id': '1120250930000001',
                'price': '2505.5',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'dhan',
            ],
        )
        self.modification = OrderModification(modify_request, stored_order)

    def run(self):
        """Builds the request, catches the error and prints its message.

        Returns:
            None: This method returns nothing.
        """
        login = {
            'access_token': 'example-token',
        }
        settings = {
            'client_id': '1000000001',
        }
        print(f'Validity after the change: {self.modification.validity}')
        try:
            self.broker_orders.build_modify_request(
                '1120250930000001',
                None,
                self.modification,
                login,
                settings,
            )
        except OrderNotReadyError as error:
            print('Answered with HTTP 503:')
            print(error)


if __name__ == '__main__':
    DhanModifyWithoutValidityExample().run()
