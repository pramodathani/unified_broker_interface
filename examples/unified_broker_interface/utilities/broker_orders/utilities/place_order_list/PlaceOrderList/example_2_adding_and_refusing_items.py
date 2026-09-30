"""Adds items to a place list one at a time with `add_item` and `refuse_item`, and shows the lists refused as a whole.

`add_item` is what the constructor calls for each item: it keeps a valid order and its engine body, or keeps a 400 refusal and None in their place, so `entries` and `bodies` always line up with the caller's list. `refuse_item` keeps a refusal directly. An item that carries its own `dry_run` is refused, because `dry_run` applies to the whole list, so no order goes live while its neighbours are only shown.

A list longer than the configured maximum, or a body with a key other than `orders` and `dry_run`, is refused as a whole with `InvalidOrderError`. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/place_order_list/PlaceOrderList/example_2_adding_and_refusing_items.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_list import (
    PlaceOrderList,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class AddingAndRefusingItemsExample:
    """Grows a place list by hand and prints its entries.

    Attributes:
        order (dict): One valid order body.
        place_list (PlaceOrderList): The list being grown.
    """

    def __init__(self):
        """Starts a live list with one valid order.

        Returns:
            None: This method returns nothing.
        """
        self.order = {
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        }
        body = {
            'orders': [
                self.order,
            ],
        }
        self.place_list = PlaceOrderList(body, 3)

    def run(self):
        """Adds and refuses items, prints the entries, then tries two bad lists.

        Returns:
            None: This method returns nothing.
        """
        item_with_dry_run = dict(self.order)
        item_with_dry_run['dry_run'] = True
        self.place_list.add_item(item_with_dry_run)
        self.place_list.add_item(42)
        self.place_list.refuse_item('refused by the caller before validation')
        print(f'Dry run: {self.place_list.dry_run}')
        for request_index, entry in enumerate(self.place_list.entries):
            if isinstance(entry, RefusedRequestError):
                print(f'{request_index}: HTTP {entry.status} {entry.body["error"]}; engine body {self.place_list.bodies[request_index]}')
                continue
            print(f'{request_index}: {entry.transaction_type} {entry.quantity}; engine body {self.place_list.bodies[request_index]}')
        bad_bodies = [
            {
                'orders': [
                    self.order,
                    self.order,
                    self.order,
                    self.order,
                ],
            },
            {
                'orders': [
                    self.order,
                ],
                'broker': 'zerodha',
            },
        ]
        for bad_body in bad_bodies:
            try:
                PlaceOrderList(bad_body, 3)
            except InvalidOrderError as error:
                print(f'Whole list refused: {error}')


if __name__ == '__main__':
    AddingAndRefusingItemsExample().run()
