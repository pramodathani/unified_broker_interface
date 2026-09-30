"""Catches the `InvalidOrderError` a malformed place body raises, as the place route does before it answers HTTP 400.

Every check of a place, modify or cancel request raises `InvalidOrderError` with a message written for the caller. The route catches it in one place and answers with the message as the body's `error`. The program validates three bodies taken from the refusals recorded in `test_runs/fixtures/order_routes.jsonl`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_request/InvalidOrderError/example_1_refused_place_body.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)


class RefusedPlaceBodyExample:
    """Validates three bad place bodies and prints the answer each would get.

    Attributes:
        bodies (list): The bodies to validate.
    """

    def __init__(self):
        """Lists the bodies.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            {
                'transaction_type': 'HOLD',
            },
            {
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'MARKET',
                'quantity': 0,
            },
            {
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
            },
        ]

    def run(self):
        """Validates each body and prints the answer.

        Returns:
            None: This method returns nothing.
        """
        for body in self.bodies:
            try:
                PlaceOrderRequest(body)
            except InvalidOrderError as error:
                answer = {
                    'error': str(error),
                }
                print(f'HTTP 400 {answer}')


if __name__ == '__main__':
    RefusedPlaceBodyExample().run()
