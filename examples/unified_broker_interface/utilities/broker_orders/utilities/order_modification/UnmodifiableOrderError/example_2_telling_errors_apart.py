"""Tells `UnmodifiableOrderError` apart from the other two errors building a modification can raise, as the modify route does.

Laying a change over a stored order can fail three ways, each answered differently: `UnmodifiableOrderError` (HTTP 409) when the stored order is one the route does not handle, `OrderNotReadyError` (HTTP 503) when Redis does not hold a value yet, and `InvalidOrderError` (HTTP 400) when the caller's change does not fit the order. The program builds three stored orders, one for each, and maps each error to its status.

The stored orders are shapes `test_runs/order_routes.py` stores. Nothing is sent to any broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_modification/UnmodifiableOrderError/example_2_telling_errors_apart.py
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
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class TellingErrorsApartExample:
    """Builds three failing modifications and prints the status each gets.

    Attributes:
        cases (list): Pairs of (label, stored normalized order).
    """

    def __init__(self):
        """Lists the three stored orders.

        Returns:
            None: This method returns nothing.
        """
        self.cases = [
            (
                'order type ICEBERG',
                {
                    'status': 'OPEN',
                    'order_type': 'ICEBERG',
                    'quantity': 10,
                },
            ),
            (
                'order type not stored yet',
                {
                    'status': 'OPEN',
                    'quantity': 10,
                },
            ),
            (
                'MARKET order given a price',
                {
                    'status': 'OPEN',
                    'order_type': 'MARKET',
                    'quantity': 10,
                },
            ),
        ]

    def status_for(self, stored_normalized_order):
        """Builds a price change over one stored order and returns the status its error is answered with.

        Args:
            stored_normalized_order (dict): The stored normalized order.

        Returns:
            str: The status and the error's class and message.
        """
        modify_request = ModifyOrderRequest(
            {
                'order_id': 'EXAMPLE1',
                'price': 2505,
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        stored_order = StoredOrder({
            'order': stored_normalized_order,
            'data': {},
        })
        try:
            OrderModification(modify_request, stored_order)
        except UnmodifiableOrderError as error:
            return f'409 UnmodifiableOrderError: {error}'
        except OrderNotReadyError as error:
            return f'503 OrderNotReadyError: {error}'
        except InvalidOrderError as error:
            return f'400 InvalidOrderError: {error}'
        return '200'

    def run(self):
        """Prints the status each case gets.

        Returns:
            None: This method returns nothing.
        """
        for label, stored_normalized_order in self.cases:
            print(f'{label}: {self.status_for(stored_normalized_order)}')


if __name__ == '__main__':
    TellingErrorsApartExample().run()
