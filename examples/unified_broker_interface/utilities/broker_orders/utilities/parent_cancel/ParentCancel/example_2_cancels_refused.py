"""Shows the cancels by `parent_id` that `ParentCancel` refuses, and one it accepts.

A cancel names an order either by the engine's `parent_id` or by a broker's `order_id`, never both, so `order_id` or `broker` beside `parent_id` is refused, and the route answers HTTP 400 before the engine is asked. A body that is not an object, that names no parent or an empty one, that gives an empty `part`, or whose `dry_run` is not a true or false value is refused too. The last body is valid and shows the command it becomes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/parent_cancel/ParentCancel/example_2_cancels_refused.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.parent_cancel import (
    ParentCancel,
)


class CancelsRefusedExample:
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
            [
                'not',
                'an object',
            ],
            {
                'part': 'root.first',
            },
            {
                'parent_id': '',
            },
            {
                'parent_id': 'P-1',
                'part': '',
            },
            {
                'parent_id': 'P-1',
                'order_id': '250915000000011',
            },
            {
                'parent_id': 'P-1',
                'broker': 'zerodha',
            },
            {
                'parent_id': 'P-1',
                'dry_run': 'perhaps',
            },
            {
                'parent_id': 'P-1',
                'part': 'root.first',
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
                cancel = ParentCancel(body, query_arguments)
            except InvalidOrderError as error:
                print(f'{body} -> HTTP 400: {error}')
                continue
            print(f'{body} -> {cancel.command_arguments()}')


if __name__ == '__main__':
    CancelsRefusedExample().run()
