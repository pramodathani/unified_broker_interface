"""Validates a modification that turns a LIMIT order into a stop-loss order, and asks which fields it changes.

`PUT /api/orders/modify` names the order and gives only the fields to change; everything else keeps the stored order's value. `ModifyOrderRequest` validates those fields and lists them in `changed_fields`, in a fixed order, so each broker's modify builder can ask `changes` whether to send a field at all. The order id and `dry_run` may also come from the query string, which a werkzeug MultiDict stands in for.

`parse_optional_choice` is the reader for fields such as `validity` that may be left out, but must be one of a few words when given. The program calls it once on the body directly to show that. Nothing is sent to any broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/modify_order_request/ModifyOrderRequest/example_1_change_price_and_type.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)


class ChangePriceAndTypeExample:
    """Validates one modification and prints what it changes.

    Attributes:
        body (dict): The caller's body.
        modify_request (ModifyOrderRequest): The validated modification.
    """

    def __init__(self):
        """Validates a change to SL with a price and a trigger price, with the order id in the query string.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'order_type': 'sl',
            'price': '2490',
            'trigger_price': '2495',
            'validity': '',
        }
        query_arguments = werkzeug.datastructures.MultiDict([
            (
                'order_id',
                '250930000000001',
            ),
            (
                'dry_run',
                '1',
            ),
        ])
        broker_names = [
            'dhan',
            'zerodha',
        ]
        self.modify_request = ModifyOrderRequest(self.body, query_arguments, broker_names)

    def run(self):
        """Prints the parsed fields and which of them change.

        Returns:
            None: This method returns nothing.
        """
        print(f'Order {self.modify_request.order_id}, broker {self.modify_request.broker}, dry run {self.modify_request.dry_run}')
        print(f'Changed fields: {self.modify_request.changed_fields}')
        print(f'order_type={self.modify_request.order_type}, price={self.modify_request.price}, trigger_price={self.modify_request.trigger_price}')
        for field_name in ModifyOrderRequest.MODIFIABLE_FIELD_NAMES:
            print(f'  changes {field_name}: {self.modify_request.changes(field_name)}')
        validities = [
            'DAY',
            'IOC',
        ]
        validity = self.modify_request.parse_optional_choice(self.body, 'validity', validities)
        print(f'Empty validity reads as: {validity}')


if __name__ == '__main__':
    ChangePriceAndTypeExample().run()
