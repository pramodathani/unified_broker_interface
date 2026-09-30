"""Validates the parameters of `DELETE /api/orders/cancel`, given in the JSON body or in the query string.

A cancel names the broker's order id and, optionally, the broker and whether this is a dry run. Some HTTP clients cannot send a body with `DELETE`, so each field is read from the JSON body first and from the query string second. `CancelOrderRequest` trims the order id, lower-cases the broker name and reads `dry_run` from text such as `yes`.

The query string is a werkzeug MultiDict, as Flask gives it. No broker is called.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/cancel_order_request/CancelOrderRequest/example_1_body_or_query_string.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)


class BodyOrQueryStringExample:
    """Validates one cancel from a body and one from a query string.

    Attributes:
        broker_names (list): Every broker's name, for checking `broker`.
    """

    def __init__(self):
        """Lists the broker names.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'dhan',
            'zerodha',
        ]

    def show(self, label, cancel_request):
        """Prints one validated cancel.

        Args:
            label (str): Where the fields came from.
            cancel_request (CancelOrderRequest): The validated cancel.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}: order_id={cancel_request.order_id!r}, broker={cancel_request.broker!r}, dry_run={cancel_request.dry_run}')

    def run(self):
        """Validates a cancel both ways and prints them.

        Returns:
            None: This method returns nothing.
        """
        from_body = CancelOrderRequest(
            {
                'order_id': ' 250930000000001 ',
                'broker': 'Zerodha',
                'dry_run': True,
            },
            werkzeug.datastructures.MultiDict(),
            self.broker_names,
        )
        self.show('From the body', from_body)
        query_arguments = werkzeug.datastructures.MultiDict([
            (
                'order_id',
                '1120250930000001',
            ),
            (
                'broker',
                'dhan',
            ),
            (
                'dry_run',
                'yes',
            ),
        ])
        from_query = CancelOrderRequest(None, query_arguments, self.broker_names)
        self.show('From the query string', from_query)


if __name__ == '__main__':
    BodyOrQueryStringExample().run()
