"""Shows the changes to a held order that `HeldOrderChange` refuses, and one quantity-only change it accepts.

A held order is kept by the virtual order book by its price and quantity alone, so changing its order type, trigger price or broker makes no sense yet, and the route refuses it with HTTP 400 before the engine is asked. A body that names no parent, or changes neither price nor quantity, is refused too. A change of quantity alone is fine, and its command carries `price` as None, meaning "leave the price".

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/held_order_change/HeldOrderChange/example_2_changes_refused.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.held_order_change import (
    HeldOrderChange,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)


class ChangesRefusedExample:
    """Tries several bodies and prints what each one becomes.

    Attributes:
        bodies (list): The bodies to try.
    """

    def __init__(self):
        """Lists the bodies to try.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            {
                'parent_id': 'P-1',
                'trigger_price': 2400,
            },
            {
                'parent_id': 'P-1',
                'broker': 'zerodha',
                'price': 2400,
            },
            {
                'price': 2400,
            },
            {
                'parent_id': 'P-1',
            },
            [
                'not',
                'an object',
            ],
            {
                'parent_id': 'P-1',
                'quantity': '5',
            },
        ]

    def run(self):
        """Validates each body and prints the command or the refusal.

        Returns:
            None: This method returns nothing.
        """
        query_arguments = werkzeug.datastructures.MultiDict()
        for body in self.bodies:
            try:
                change = HeldOrderChange(body, query_arguments)
            except InvalidOrderError as error:
                print(f'{body} -> HTTP 400: {error}')
                continue
            print(f'{body} -> {change.command_arguments()}')


if __name__ == '__main__':
    ChangesRefusedExample().run()
