"""Lays a caller's change over a stored order to get the whole order after the change, then converts its quantity into a broker's terms.

A broker's modify request often needs the whole order, not just what changed. `OrderModification` starts from the stored normalized order and puts each field the caller gave in its place. Here an open LIMIT buy of 10 RELIANCE at 2500 becomes an SL order with a new trigger price; the stored price is carried over because both order types take one.

`changes` tells a builder which fields the caller actually gave, and `with_quantities` returns a copy carrying quantities in the broker's own terms, leaving the original untouched. The stored order is the open LIMIT order `test_runs/order_routes.py` stores. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_modification/OrderModification/example_1_limit_to_stop_loss.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class LimitToStopLossExample:
    """Builds the order after the change and prints its fields.

    Attributes:
        modification (OrderModification): The order after the change.
    """

    def __init__(self):
        """Validates the change and lays it over the stored order.

        Returns:
            None: This method returns nothing.
        """
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'order_id': '250930000000001',
                'instrument_token': '2885',
                'tradingsymbol': 'RELIANCE',
                'exchange': 'NSE',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'disclosed_quantity': 0,
                'price': 2500.0,
                'trigger_price': 0.0,
                'tag': None,
            },
            'data': {},
        })
        modify_request = ModifyOrderRequest(
            {
                'order_id': '250930000000001',
                'order_type': 'SL',
                'trigger_price': '2495',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        self.modification = OrderModification(modify_request, stored_order)

    def run(self):
        """Prints the order after the change and a copy with converted quantities.

        Returns:
            None: This method returns nothing.
        """
        print(f'{self.modification.transaction_type} {self.modification.quantity} {self.modification.tradingsymbol} on {self.modification.exchange} ({self.modification.product})')
        print(f'order_type={self.modification.order_type}, validity={self.modification.validity}')
        print(f'price={self.modification.price} ({self.modification.price_text}), trigger_price={self.modification.trigger_price} ({self.modification.trigger_price_text})')
        print(f'Changed by the caller: {self.modification.changed_fields}')
        print(f'changes price: {self.modification.changes("price")}, changes trigger_price: {self.modification.changes("trigger_price")}')
        in_lots = self.modification.with_quantities(2, 0)
        print(f'Copy in broker terms: quantity={in_lots.quantity}; original still {self.modification.quantity}')


if __name__ == '__main__':
    LimitToStopLossExample().run()
