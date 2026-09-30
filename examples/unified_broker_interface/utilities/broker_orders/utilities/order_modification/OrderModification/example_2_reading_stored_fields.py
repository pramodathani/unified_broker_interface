"""Uses the stored-field readers of `OrderModification` directly, to show how each treats a missing or odd value.

The readers decide what happens when Redis holds less than a modify request needs. `stored_text` trims a value and treats an empty one as missing. `stored_word` requires one of the route's words and raises `OrderNotReadyError` when nothing is stored, or `UnmodifiableOrderError` when the word is one the route does not handle. `stored_optional_word` lets a missing value through as None. `stored_quantity` reads a whole number, and gives 0 for a missing optional quantity. `merged_price` decides a price after the change: the caller's when given, otherwise the stored one, but only when both the old and new order types take it.

The program first builds a modification from a LIMIT order changed to SL with a trigger price, which carries the stored limit price over, then calls each reader on a small stored order in which the price is empty. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_modification/OrderModification/example_2_reading_stored_fields.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    UnmodifiableOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class ReadingStoredFieldsExample:
    """Builds a modification and calls each of its readers.

    Attributes:
        modify_request (ModifyOrderRequest): The change to SL with a trigger price.
        modification (OrderModification): The order after the change.
        stored (dict): A small stored order for the readers.
    """

    def __init__(self):
        """Builds the modification and the small stored order.

        Returns:
            None: This method returns nothing.
        """
        self.modify_request = ModifyOrderRequest(
            {
                'order_id': 'MODSTOPLOSS',
                'order_type': 'SL',
                'trigger_price': '2495',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'SELL',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {},
        })
        self.modification = OrderModification(self.modify_request, stored_order)
        self.stored = {
            'tradingsymbol': '  RELIANCE ',
            'validity': 'GTT',
            'quantity': '10',
            'disclosed_quantity': None,
            'price': '',
        }

    def run(self):
        """Prints what each reader gives or raises.

        Returns:
            None: This method returns nothing.
        """
        print(f'After the change: order_type={self.modification.order_type}, price={self.modification.price}, trigger_price={self.modification.trigger_price}, validity={self.modification.validity}, product={self.modification.product}')
        validities = [
            'DAY',
            'IOC',
        ]
        products = [
            'CNC',
            'MIS',
            'NRML',
        ]
        print(f'stored_text tradingsymbol: {self.modification.stored_text(self.stored, "tradingsymbol")!r}')
        print(f'stored_text price: {self.modification.stored_text(self.stored, "price")!r}')
        print(f'stored_optional_word product: {self.modification.stored_optional_word(self.stored, "product", products)}')
        try:
            self.modification.stored_word(self.stored, 'validity', validities)
        except UnmodifiableOrderError as error:
            print(f'stored_word validity: UnmodifiableOrderError: {error}')
        try:
            self.modification.stored_word(self.stored, 'product', products)
        except OrderNotReadyError as error:
            print(f'stored_word product: OrderNotReadyError: {error}')
        print(f'stored_quantity quantity: {self.modification.stored_quantity(self.stored, "quantity", True)}')
        print(f'stored_quantity disclosed_quantity: {self.modification.stored_quantity(self.stored, "disclosed_quantity", False)}')
        merged = self.modification.merged_price(self.modify_request, self.stored, 'trigger_price', self.modify_request.trigger_price, True, False)
        print(f'merged_price trigger_price given by the caller: {merged}')
        try:
            self.modification.merged_price(self.modify_request, self.stored, 'price', None, True, True)
        except OrderNotReadyError as error:
            print(f'merged_price price with nothing stored: OrderNotReadyError: {error}')
        try:
            self.modification.merged_price(self.modify_request, self.stored, 'price', None, True, False)
        except InvalidOrderError as error:
            print(f'merged_price price for an order type that took none before: InvalidOrderError: {error}')


if __name__ == '__main__':
    ReadingStoredFieldsExample().run()
