"""Validates a cancel list that names some orders by broker order id and others by the engine's `parent_id`, with one `dry_run` for the whole list.

`DELETE /api/orders/cancel` takes a list mixing both kinds of item. Given `ParentCancel` as its last argument, `OrderChangeList` validates an item naming `parent_id` with that class and hands it the list's own `dry_run`, so a dry run of the list cannot cancel an order the engine manages while its neighbours are only shown. `names_broker_order` tells the two kinds apart, and `order_ids` lists only the broker order ids, since a parent is not looked up in any broker's order book.

`dry_run` belongs beside `orders`, so an item that carries its own is refused on its own, as is an item giving `broker` beside `parent_id`. Nothing is sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_change_list/OrderChangeList/example_3_items_named_by_parent.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_change_list import (
    OrderChangeList,
)
from unified_broker_interface.utilities.broker_orders.utilities.parent_cancel import (
    ParentCancel,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class ItemsNamedByParentExample:
    """Validates the mixed list and prints what each entry became.

    Attributes:
        change_list (OrderChangeList): The validated list.
    """

    def __init__(self):
        """Validates six cancels as a dry run: two broker orders, a whole parent, a plan part, a parent carrying its own `dry_run`, and a parent with `broker` beside it.

        Returns:
            None: This method returns nothing.
        """
        body = {
            'orders': [
                {
                    'order_id': '250915000000011',
                    'broker': 'zerodha',
                },
                {
                    'parent_id': 'P-00000000000040008000000000000001',
                },
                {
                    'parent_id': 'P-00000000000040008000000000000002',
                    'part': 'root.each_fill.children.1',
                },
                {
                    'order_id': '112509150000012',
                },
                {
                    'parent_id': 'P-00000000000040008000000000000003',
                    'dry_run': False,
                },
                {
                    'parent_id': 'P-00000000000040008000000000000003',
                    'broker': 'zerodha',
                },
            ],
            'dry_run': True,
        }
        broker_names = [
            'dhan',
            'zerodha',
        ]
        self.change_list = OrderChangeList(
            body,
            werkzeug.datastructures.MultiDict(),
            CancelOrderRequest,
            broker_names,
            ParentCancel,
        )

    def describe(self, entry):
        """Describes one entry of the list in a line.

        Args:
            entry (CancelOrderRequest | ParentCancel | RefusedRequestError): One validated entry, or its refusal.

        Returns:
            str: The entry's class and the fields that name the order.
        """
        if isinstance(entry, RefusedRequestError):
            return f"RefusedRequestError {entry.status}: {entry.body['error']}"
        if isinstance(entry, ParentCancel):
            return f'ParentCancel {entry.parent_id} part {entry.part}, dry_run {entry.dry_run}, cancel_parent arguments {entry.command_arguments()}'
        return f'CancelOrderRequest {entry.order_id} at {entry.broker}'

    def run(self):
        """Prints each entry, whether it names a broker order, and the order ids to look up.

        Returns:
            None: This method returns nothing.
        """
        print(f'Dry run of the list: {self.change_list.dry_run}')
        for request_index, entry in enumerate(self.change_list.entries):
            print(f'request {request_index}: {self.describe(entry)}')
            if not isinstance(entry, RefusedRequestError):
                print(f'  names_broker_order: {self.change_list.names_broker_order(entry)}')
        print(f'Order ids to look up: {self.change_list.order_ids()}')


if __name__ == '__main__':
    ItemsNamedByParentExample().run()
