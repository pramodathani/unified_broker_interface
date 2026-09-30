"""Catches the `UnmodifiableOrderError` raised for a bracket order, which the modify route does not change.

The modify route only handles orders whose product is CNC, MIS or NRML. A bracket order (`BO`) placed elsewhere carries legs the route knows nothing about, so laying a change over it raises `UnmodifiableOrderError`, answered with HTTP 409 Conflict and the error's message.

The stored order is the `MODBRACKET` case from `test_runs/order_routes.py`. Nothing is sent to any broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_modification/UnmodifiableOrderError/example_1_bracket_order.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    UnmodifiableOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class BracketOrderExample:
    """Tries to modify a stored bracket order.

    Attributes:
        modify_request (ModifyOrderRequest): The caller's change of price.
        stored_order (StoredOrder): The bracket order.
    """

    def __init__(self):
        """Builds the change and the stored order.

        Returns:
            None: This method returns nothing.
        """
        self.modify_request = ModifyOrderRequest(
            {
                'order_id': 'MODBRACKET',
                'price': 2505,
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
                'product': 'BO',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {},
        })

    def run(self):
        """Catches the error and prints the answer it becomes.

        Returns:
            None: This method returns nothing.
        """
        try:
            OrderModification(self.modify_request, self.stored_order)
        except UnmodifiableOrderError as error:
            print(f'HTTP 409: {error}')


if __name__ == '__main__':
    BracketOrderExample().run()
