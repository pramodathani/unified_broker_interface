"""Validates a new trigger and limit price for the stop of a bracket plan that has not been sent yet, and builds the engine command it becomes.

A plan's exits wait for its entry to fill before anything is sent, so they have no broker order id yet. The modify route names one by the plan's `parent_id` and its `part` path, as `GET /api/orders/parents` shows it, and a part can change its `trigger_price` as well as its price and quantity. `command_arguments` then carries `part` and `trigger_price` too, which the engine's `modify_held` command hands to the plan. A body that names no part cannot change a trigger price, and a part cannot change its order type; both are refused here.

Nothing is sent to the engine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/held_order_change/HeldOrderChange/example_3_plan_part_stop.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.held_order_change import (
    HeldOrderChange,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)


class PlanPartStopExample:
    """Validates a change to a plan part, and two changes that are refused.

    Attributes:
        query_arguments (werkzeug.datastructures.MultiDict): An empty query string.
    """

    def __init__(self):
        """Builds the empty query string the changes are read with.

        Returns:
            None: This method returns nothing.
        """
        self.query_arguments = werkzeug.datastructures.MultiDict()

    def show_refusal(self, body):
        """Prints why a body is refused.

        Args:
            body (dict): The request body.

        Returns:
            None: This method returns nothing.
        """
        try:
            HeldOrderChange(body, self.query_arguments)
        except InvalidOrderError as error:
            print(f'Refused: {error}')

    def run(self):
        """Prints the parsed part change, its command arguments, and the refusals.

        Returns:
            None: This method returns nothing.
        """
        change = HeldOrderChange(
            {
                'parent_id': 'P-00000000000040008000000000000001',
                'part': 'root.each_fill.children.0',
                'trigger_price': '2440',
                'price': '2438.5',
            },
            self.query_arguments,
        )
        print(f'Part: {change.part}')
        print(f'Trigger price: {change.trigger_price!r}')
        print(f'Price: {change.price!r}')
        print(f'modify_held arguments: {change.command_arguments()}')
        self.show_refusal({
            'parent_id': 'P-00000000000040008000000000000001',
            'trigger_price': '2440',
        })
        self.show_refusal({
            'parent_id': 'P-00000000000040008000000000000001',
            'part': 'root.each_fill.children.0',
            'order_type': 'LIMIT',
        })


if __name__ == '__main__':
    PlanPartStopExample().run()
