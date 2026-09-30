"""Validates a list of modifications with bad items among good ones, and calls the item checks directly.

`PUT /api/orders/modify` takes the same `orders` list form as cancel. `parse_item` validates one item: an item that is not an object, that carries its own `dry_run`, or that is not a valid modification becomes a 400 refusal while its neighbours stand. `refuse_repeated_orders` then replaces any item naming an order already named; two items for the same order id at two different brokers are different orders and both stand.

A body whose `orders` is missing, or that carries a key other than `orders` and `dry_run`, is refused as a whole, which the program also shows. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_change_list/OrderChangeList/example_2_modify_items_one_by_one.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_change_list import (
    OrderChangeList,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class ModifyItemsOneByOneExample:
    """Validates a list of modifications and prints what each item became.

    Attributes:
        broker_names (list): Every broker's name.
        change_list (OrderChangeList): The validated list.
    """

    def __init__(self):
        """Validates a list with two good, one repeated and two bad items.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'dhan',
            'shoonya',
            'flattrade',
        ]
        body = {
            'orders': [
                {
                    'order_id': '26091500000021',
                    'broker': 'flattrade',
                    'price': 2501,
                },
                {
                    'order_id': '26091500000021',
                    'broker': 'shoonya',
                    'price': 2502,
                },
                {
                    'order_id': '26091500000021',
                    'broker': 'shoonya',
                    'quantity': 5,
                },
                'not an object',
                {
                    'order_id': '112509150000012',
                    'price': 2500,
                    'dry_run': True,
                },
            ],
        }
        query_arguments = werkzeug.datastructures.MultiDict([
            (
                'dry_run',
                'true',
            ),
        ])
        self.change_list = OrderChangeList(body, query_arguments, ModifyOrderRequest, self.broker_names)

    def describe(self, entry):
        """Describes one entry of the list.

        Args:
            entry (ModifyOrderRequest | RefusedRequestError): The entry.

        Returns:
            str: A one-line description.
        """
        if isinstance(entry, RefusedRequestError):
            return f'refused with {entry.status}: {entry.body["error"]}'
        return f'modify {entry.order_id} at {entry.broker}, changing {entry.changed_fields}'

    def run(self):
        """Prints every entry, then calls the item checks directly and shows whole-list refusals.

        Returns:
            None: This method returns nothing.
        """
        print(f'Dry run for the whole list: {self.change_list.dry_run}')
        for request_index, entry in enumerate(self.change_list.entries):
            print(f'{request_index}: {self.describe(entry)}')
        print(f'Order ids to look up: {self.change_list.order_ids()}')
        item = {
            'order_id': '112509150000012',
            'order_type': 'STOP',
        }
        print(f'parse_item alone: {self.describe(self.change_list.parse_item(item, ModifyOrderRequest, self.broker_names))}')
        unnamed_broker_item = {
            'order_id': '26091500000021',
            'price': 1,
        }
        self.change_list.entries.append(self.change_list.parse_item(unnamed_broker_item, ModifyOrderRequest, self.broker_names))
        self.change_list.refuse_repeated_orders()
        print(f'Added an item with no broker, then checked for repeats: {self.describe(self.change_list.entries[-1])}')
        bad_bodies = [
            {
                'orders': [],
            },
            {
                'orders': [
                    {
                        'order_id': '1',
                    },
                ],
                'broker': 'dhan',
            },
        ]
        for bad_body in bad_bodies:
            try:
                OrderChangeList(bad_body, werkzeug.datastructures.MultiDict(), ModifyOrderRequest, self.broker_names)
            except InvalidOrderError as error:
                print(f'Whole list refused: {error}')


if __name__ == '__main__':
    ModifyItemsOneByOneExample().run()
