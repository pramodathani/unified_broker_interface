"""Uses the field readers every order route request shares, on a body a caller might send.

`OrderRequest` is the base of the place, modify and cancel requests. It holds no state of its own, only the readers that turn loosely typed JSON and query string values into checked Python values: flags that may be `true` or `"yes"`, upper-case choices, whole numbers, prices as `Decimal`, order ids and broker names. Each reader raises `InvalidOrderError` with a caller-facing message when the value does not fit.

The program builds a bare `OrderRequest` and calls each reader directly, first on good values and then on a few bad ones, so the messages can be seen. The query string is a werkzeug MultiDict, as Flask gives it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_request/OrderRequest/example_1_reading_request_fields.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)


class ReadingRequestFieldsExample:
    """Reads every kind of field from one body and shows three refusals.

    Attributes:
        order_request (OrderRequest): The request whose readers are used.
        body (dict): The body the fields are read from.
        query_arguments (werkzeug.datastructures.MultiDict): The query string.
        broker_names (list): Every broker's name.
    """

    def __init__(self):
        """Builds the request, the body and the query string.

        Returns:
            None: This method returns nothing.
        """
        self.order_request = OrderRequest()
        self.body = {
            'order_type': 'limit',
            'quantity': '25',
            'price': '2500.50',
            'dry_run': 'yes',
            'broker': 'Zerodha',
        }
        self.query_arguments = werkzeug.datastructures.MultiDict([
            (
                'order_id',
                '250930000000001',
            ),
        ])
        self.broker_names = [
            'dhan',
            'zerodha',
        ]

    def run(self):
        """Reads each field, then shows three refusals.

        Returns:
            None: This method returns nothing.
        """
        order_types = [
            'MARKET',
            'LIMIT',
        ]
        validities = [
            'DAY',
            'IOC',
        ]
        order_type = self.order_request.parse_choice(self.body, 'order_type', None, order_types)
        validity = self.order_request.parse_choice(self.body, 'validity', 'DAY', validities)
        quantity = self.order_request.parse_whole_number(self.body, 'quantity', 1)
        price = self.order_request.parse_price(self.body, 'price')
        dry_run = self.order_request.parse_flag('dry_run', self.body['dry_run'])
        order_id = self.order_request.parse_order_id(self.body, self.query_arguments)
        broker = self.order_request.parse_broker(self.body, self.query_arguments, self.broker_names)
        print(f'order_type={order_type}, validity={validity}, quantity={quantity}, price={price!r}')
        print(f'dry_run={dry_run}, order_id={order_id}, broker={broker}')
        bad_body = {
            'quantity': '2.5',
            'price': '-1',
        }
        try:
            self.order_request.parse_whole_number(bad_body, 'quantity', 1)
        except InvalidOrderError as error:
            print(f'Refused: {error}')
        try:
            self.order_request.parse_price(bad_body, 'price')
        except InvalidOrderError as error:
            print(f'Refused: {error}')
        try:
            self.order_request.parse_flag('after_market', 'perhaps')
        except InvalidOrderError as error:
            print(f'Refused: {error}')


if __name__ == '__main__':
    ReadingRequestFieldsExample().run()
