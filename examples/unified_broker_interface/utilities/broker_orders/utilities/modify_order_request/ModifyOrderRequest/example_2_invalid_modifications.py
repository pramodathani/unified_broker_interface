"""Shows the modifications `ModifyOrderRequest` refuses with HTTP 400, and a quantity-only change it accepts.

A modification must change at least one field; a disclosed quantity cannot be more than the new quantity; and an order type or validity must be one of the route's words. `parse_optional_choice` enforces the last rule and is also called directly here on a bad validity, which shows its message.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/modify_order_request/ModifyOrderRequest/example_2_invalid_modifications.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)


class InvalidModificationsExample:
    """Validates several modifications and prints what each becomes.

    Attributes:
        bodies (list): The bodies to try.
        broker_names (list): Every broker's name.
    """

    def __init__(self):
        """Lists the bodies and broker names.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            {
                'order_id': '250930000000001',
            },
            {
                'order_id': '250930000000001',
                'quantity': 5,
                'disclosed_quantity': 10,
            },
            {
                'order_id': '250930000000001',
                'order_type': 'ICEBERG',
            },
            {
                'order_id': '250930000000001',
                'quantity': '20',
            },
        ]
        self.broker_names = [
            'zerodha',
        ]

    def run(self):
        """Validates each body, then calls the optional choice reader on a bad validity.

        Returns:
            None: This method returns nothing.
        """
        query_arguments = werkzeug.datastructures.MultiDict()
        accepted = None
        for body in self.bodies:
            try:
                accepted = ModifyOrderRequest(body, query_arguments, self.broker_names)
            except InvalidOrderError as error:
                print(f'{body} -> HTTP 400: {error}')
                continue
            print(f'{body} -> changes {accepted.changed_fields}, quantity {accepted.quantity}, changes price: {accepted.changes("price")}')
        bad_validity = {
            'validity': 'GTC',
        }
        validities = [
            'DAY',
            'IOC',
        ]
        try:
            accepted.parse_optional_choice(bad_validity, 'validity', validities)
        except InvalidOrderError as error:
            print(f'validity GTC -> HTTP 400: {error}')


if __name__ == '__main__':
    InvalidModificationsExample().run()
