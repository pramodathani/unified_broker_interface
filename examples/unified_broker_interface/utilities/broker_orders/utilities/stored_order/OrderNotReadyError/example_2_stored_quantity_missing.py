"""Catches the `OrderNotReadyError` raised when a stored order has no whole-number quantity to modify.

A modification sends the order's total quantity, so `OrderModification` reads it from the stored order even when the caller changes only the price. When a websocket update has stored the order before its quantity arrived, there is nothing to send, and the modification raises `OrderNotReadyError` as it is built. The same error can be raised directly, which the program also shows, and both are answered with HTTP 503.

The stored order is the `MODNOQUANTITY` case from `test_runs/order_routes.py`. Nothing is sent to any broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/stored_order/OrderNotReadyError/example_2_stored_quantity_missing.py
"""

import werkzeug.datastructures

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


class StoredQuantityMissingExample:
    """Builds a modification for an order with no stored quantity, and raises the error by hand.

    Attributes:
        modify_request (ModifyOrderRequest): The caller's change of price.
        stored_order (StoredOrder): The order without a quantity.
    """

    def __init__(self):
        """Builds the request and the stored order.

        Returns:
            None: This method returns nothing.
        """
        self.modify_request = ModifyOrderRequest(
            {
                'order_id': 'MODNOQUANTITY',
                'price': 2501,
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        self.stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': None,
                'price': 2500.0,
            },
            'data': {},
        })

    def raise_by_hand(self):
        """Raises the error the way a broker's own check would.

        Returns:
            None: This method returns nothing.

        Raises:
            OrderNotReadyError: Always.
        """
        raise OrderNotReadyError('Redis does not hold this order yet')

    def run(self):
        """Catches both errors and prints their messages.

        Returns:
            None: This method returns nothing.
        """
        try:
            OrderModification(self.modify_request, self.stored_order)
        except OrderNotReadyError as error:
            print(f'From the modification: {error}')
        try:
            self.raise_by_hand()
        except OrderNotReadyError as error:
            print(f'Raised by hand: {error}')
            print(f'Is an Exception: {isinstance(error, Exception)}')


if __name__ == '__main__':
    StoredQuantityMissingExample().run()
