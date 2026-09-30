"""Validates a list of three orders to place, one of them invalid, and builds the list answer.

`POST /api/orders/place` also takes a body with an `orders` list. Each item is validated as a single order would be; an invalid item gets its own 400 entry and the others still go to the order engine. `bodies` holds what the engine is handed for each valid item: the item with `dry_run` copied from the list and any `broker` removed, since the engine chooses the broker.

`results` turns one `(body, status)` answer per item into the list answer, picking up the `intent_id` the engine gave each order. The engine's answers here are written by hand in the shape recorded in `test_runs/fixtures/order_routes.jsonl`; nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/place_order_list/PlaceOrderList/example_1_three_orders_one_bad.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.place_order_list import (
    PlaceOrderList,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class ThreeOrdersOneBadExample:
    """Validates the list and prints the engine bodies and the answer.

    Attributes:
        place_list (PlaceOrderList): The validated list.
    """

    def __init__(self):
        """Validates two good orders and one without a quantity, as a dry run.

        Returns:
            None: This method returns nothing.
        """
        body = {
            'dry_run': True,
            'orders': [
                {
                    'instrument_id': '11111111-1111-5111-8111-000000000001',
                    'transaction_type': 'BUY',
                    'product': 'MIS',
                    'order_type': 'MARKET',
                    'quantity': 10,
                    'broker': 'zerodha',
                },
                {
                    'instrument_id': '11111111-1111-5111-8111-000000000002',
                    'transaction_type': 'SELL',
                    'product': 'MIS',
                    'order_type': 'MARKET',
                },
                {
                    'instrument_id': '11111111-1111-5111-8111-000000000003',
                    'transaction_type': 'SELL',
                    'product': 'CNC',
                    'order_type': 'LIMIT',
                    'price': '101.5',
                    'quantity': 5,
                },
            ],
        }
        self.place_list = PlaceOrderList(body, 20)

    def run(self):
        """Prints each item's engine body, then the list answer.

        Returns:
            None: This method returns nothing.
        """
        answers = []
        for request_index, entry in enumerate(self.place_list.entries):
            if isinstance(entry, RefusedRequestError):
                answers.append((
                    entry.body,
                    entry.status,
                ))
                continue
            engine_body = self.place_list.bodies[request_index]
            print(f'Engine body {request_index}: {engine_body}')
            answer_body = {
                'intent_id': f'0000000000004000800000000000000{request_index}',
                'dry_run': True,
                'instrument_id': entry.instrument_id,
            }
            answers.append((
                answer_body,
                200,
            ))
        print(json.dumps(self.place_list.results(answers), indent=2))


if __name__ == '__main__':
    ThreeOrdersOneBadExample().run()
