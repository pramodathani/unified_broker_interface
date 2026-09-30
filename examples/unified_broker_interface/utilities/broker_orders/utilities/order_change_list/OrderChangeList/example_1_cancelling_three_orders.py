"""Validates a list of three cancels, one of which repeats an earlier one, and builds the list answer.

`DELETE /api/orders/cancel` also takes a body with an `orders` list. Each item is validated as a single cancel would be, and an item that names an order an earlier item already names is replaced with its own 400 refusal, because two changes to one order in one request are almost always a mistake. The other items are still answered.

`order_ids` lists the distinct order ids to look up in the brokers' order books, and `results` turns one `(body, status)` answer per item into the list answer. The answers here are written by hand in the shape the single cancel route gives, instead of sending anything.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_change_list/OrderChangeList/example_1_cancelling_three_orders.py
"""

import json

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_change_list import (
    OrderChangeList,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class CancellingThreeOrdersExample:
    """Validates the list and prints its entries and answer.

    Attributes:
        change_list (OrderChangeList): The validated list.
    """

    def __init__(self):
        """Validates three cancels, the third repeating the first.

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
                    'order_id': '112509150000012',
                },
                {
                    'order_id': '250915000000011',
                },
            ],
            'dry_run': True,
        }
        broker_names = [
            'dhan',
            'zerodha',
        ]
        self.change_list = OrderChangeList(body, werkzeug.datastructures.MultiDict(), CancelOrderRequest, broker_names)

    def run(self):
        """Prints each entry, the order ids to look up, and the list answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'Dry run: {self.change_list.dry_run}')
        answers = []
        for entry in self.change_list.entries:
            if isinstance(entry, RefusedRequestError):
                print(f'Refused: {entry.body}')
                answers.append((
                    entry.body,
                    entry.status,
                ))
                continue
            print(f'Cancel {entry.order_id} at {entry.broker}')
            answer_body = {
                'order_id': entry.order_id,
                'dry_run': True,
            }
            answers.append((
                answer_body,
                200,
            ))
        print(f'Order ids to look up: {self.change_list.order_ids()}')
        print(json.dumps(self.change_list.results(answers), indent=2))


if __name__ == '__main__':
    CancellingThreeOrdersExample().run()
