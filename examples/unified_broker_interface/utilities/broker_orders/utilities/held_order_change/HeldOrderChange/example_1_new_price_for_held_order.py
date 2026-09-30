"""Validates a change of price for an order the order engine is still holding, and builds the engine command it becomes.

A virtual limit order is held by the order engine until the market reaches it, so it has no broker order id yet. The modify route names it by the `parent_id` the place route answered with, and only its price and quantity can change. `HeldOrderChange` checks that and `command_arguments` gives the arguments of the engine's `modify_held` command, with the price as text so it survives JSON unchanged.

The body here comes as JSON and `dry_run` comes from the query string, which a MultiDict stands in for, as it does inside Flask. Nothing is sent to the engine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/held_order_change/HeldOrderChange/example_1_new_price_for_held_order.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.held_order_change import (
    HeldOrderChange,
)


class NewPriceForHeldOrderExample:
    """Validates one change and prints the engine command's arguments.

    Attributes:
        change (HeldOrderChange): The validated change.
    """

    def __init__(self):
        """Validates a new price and quantity for a held order, as a dry run.

        Returns:
            None: This method returns nothing.
        """
        body = {
            'parent_id': 'P-00000000000040008000000000000001',
            'price': '2498.35',
            'quantity': 20,
        }
        query_arguments = werkzeug.datastructures.MultiDict([
            (
                'dry_run',
                'true',
            ),
        ])
        self.change = HeldOrderChange(body, query_arguments)

    def run(self):
        """Prints the parsed fields and the command arguments.

        Returns:
            None: This method returns nothing.
        """
        print(f'Parent: {self.change.parent_id}')
        print(f'Price: {self.change.price!r}')
        print(f'Quantity: {self.change.quantity}')
        print(f'Dry run: {self.change.dry_run}')
        print(f'modify_held arguments: {self.change.command_arguments()}')


if __name__ == '__main__':
    NewPriceForHeldOrderExample().run()
