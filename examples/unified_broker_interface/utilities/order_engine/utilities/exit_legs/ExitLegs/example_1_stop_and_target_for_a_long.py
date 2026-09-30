"""Builds the stop and target orders that protect a long position, as a bracket order does once its entry fills.

A bracket order buys, and then protects what it bought with a stop below and a target above. `ExitLegs.build` takes the caller's validated entry order, the caller's `synthetic` parameters and the filled quantity, and answers with the two exit orders, each a copy of the entry with the side turned round. This program validates a real `POST /api/orders/place` body into a `PlaceOrderRequest`, which reads nothing but the body, and builds the exits for 100 shares.

Nothing is sent to a broker and nothing is read from a store. Notice that the stop is a stop-limit (`SL`) with both its trigger and its limit as the caller gave them, that the target is a plain `LIMIT`, that both sell because the entry bought, that both keep the entry's product and instrument, and that neither carries the caller's tag, since the caller did not ask for these orders by name. The program also calls `exit_order` and `price` on their own.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/exit_legs/ExitLegs/example_1_stop_and_target_for_a_long.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
)


class StopAndTargetExample:
    """Builds the exits for a filled buy and prints each one.

    Attributes:
        exit_legs (ExitLegs): The builder being shown.
        entry (PlaceOrderRequest): The caller's entry order.
        parameters (dict): The caller's `synthetic` object.
    """

    def __init__(self):
        """Validates the entry order and sets the exit prices.

        Returns:
            None: This method returns nothing.
        """
        self.exit_legs = ExitLegs()
        self.entry = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'quantity': 100,
            'price': '1000.00',
            'tag': 'swing42',
        })
        self.parameters = {
            'type': 'bracket',
            'stop_price': '990.00',
            'stop_limit_price': '988.00',
            'target_price': '1010.00',
        }

    def run(self):
        """Prints the entry and the exits built for it.

        Returns:
            None: This method returns nothing.
        """
        print(f'Entry: {self.entry.transaction_type} {self.entry.quantity} {self.entry.order_type} at {self.entry.price}, tag {self.entry.tag}')
        for role, order in self.exit_legs.build(self.entry, self.parameters, 100):
            print(f'{role}: {order.transaction_type} {order.quantity} {order.product} {order.order_type} price {order.price_text} trigger {order.trigger_price_text} instrument {order.instrument_id} tag {order.tag}')
        print(f'Entry still: {self.entry.transaction_type} {self.entry.quantity}, tag {self.entry.tag}')
        half_target = self.exit_legs.exit_order(self.entry, 'SELL', 50, 'LIMIT', decimal.Decimal('1005.00'), None)
        print(f'exit_order for half at 1005: {half_target.transaction_type} {half_target.quantity} {half_target.order_type} price {half_target.price_number} trigger {half_target.trigger_price_number}')
        print(f'price of target_price: {self.exit_legs.price(self.parameters, "target_price")!r}')
        print(f'price of a missing field: {self.exit_legs.price(self.parameters, "trail_price")}')


if __name__ == '__main__':
    StopAndTargetExample().run()
