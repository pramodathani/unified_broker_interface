"""Shows the cancels `CancelOrderRequest` refuses with HTTP 400 before any broker is looked up.

Each refusal is an `InvalidOrderError` whose message the route answers with. The program tries a missing order id, an order id with characters no broker uses, a broker that does not exist, a `dry_run` that is neither true nor false, and a body that is a list rather than an object.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/cancel_order_request/CancelOrderRequest/example_2_invalid_cancels.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)


class InvalidCancelsExample:
    """Validates several bad cancels and prints each refusal.

    Attributes:
        bodies (list): The bodies to try.
        broker_names (list): Every broker's name.
    """

    def __init__(self):
        """Lists the bodies and the broker names.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            {},
            {
                'order_id': 'ORDER 1; DROP',
            },
            {
                'order_id': '250930000000001',
                'broker': 'robinhood',
            },
            {
                'order_id': '250930000000001',
                'dry_run': 'maybe',
            },
            [
                '250930000000001',
            ],
        ]
        self.broker_names = [
            'dhan',
            'zerodha',
        ]

    def run(self):
        """Validates each body and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        query_arguments = werkzeug.datastructures.MultiDict()
        for body in self.bodies:
            try:
                CancelOrderRequest(body, query_arguments, self.broker_names)
            except InvalidOrderError as error:
                print(f'{body} -> HTTP 400: {error}')


if __name__ == '__main__':
    InvalidCancelsExample().run()
