"""Reads one open Zerodha order the way the cancel and modify routes read it from Redis.

Each broker's order scripts keep a hash `<broker>:orders:orders` whose values are JSON entries holding the normalized order under `order` and the broker's own copy under `data`. The routes decode one entry and wrap it in a `StoredOrder`, which gives them the normalized status, the broker's own fields, and whether the order is already finished.

The entry below is the shape `test_runs/order_routes.py` stores for an open after-market Zerodha order. Zerodha's cancel request needs the `variety` from the broker's own copy, which is why the program prints it. No Redis is used: the entry is decoded from a string.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/stored_order/StoredOrder/example_1_open_zerodha_order.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class OpenZerodhaOrderExample:
    """Decodes an open order's hash entry and prints what the routes read from it.

    Attributes:
        stored_order (StoredOrder): The order being shown.
    """

    def __init__(self):
        """Decodes the entry as Redis would hold it.

        Returns:
            None: This method returns nothing.
        """
        entry_text = json.dumps({
            'order': {
                'status': 'OPEN',
                'order_id': '250930000000001',
                'tradingsymbol': 'RELIANCE',
                'exchange': 'NSE',
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'variety': 'amo',
                'status': 'AMO REQ RECEIVED',
            },
        })
        self.stored_order = StoredOrder(json.loads(entry_text))

    def run(self):
        """Prints the order's status, its broker fields and whether it is finished.

        Returns:
            None: This method returns nothing.
        """
        print(f'Normalized status: {self.stored_order.status}')
        print(f'Broker status: {self.stored_order.data["status"]}')
        print(f'Variety for the cancel URL: {self.stored_order.data["variety"]}')
        print(f'Symbol: {self.stored_order.order["tradingsymbol"]}, quantity: {self.stored_order.order["quantity"]}')
        print(f'Finished: {self.stored_order.is_finished()}')


if __name__ == '__main__':
    OpenZerodhaOrderExample().run()
