"""Turns an `OrderBookFilterError` into a 400 answer, and shows that it is a `ValueError`.

`OrderBookFilterError` subclasses `ValueError`, so code that already catches `ValueError` catches it too. The order book routes build the filter from the query string once they have read the day's document, and when this error is raised they answer 400 with `{"error": message}` instead of the document.

This program writes a small answering class that does what a route does: build the filter, and either narrow a tiny order book or answer 400 with the error's message. The order book is in memory and nothing touches Redis.

Notice that the good request is answered 200 with one order, that the bad one is answered 400 with the message, and that catching `ValueError` also catches the error.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_book_filter/OrderBookFilterError/example_2_answering_bad_request.py
"""

import json

from werkzeug.datastructures import MultiDict

from unified_broker_interface.utilities.order_book_filter import (
    OrderBookFilter,
    OrderBookFilterError,
)


class AnsweringBadRequestExample:
    """Answers one good and one bad order book request.

    Attributes:
        document (dict): The day's order book.
    """

    def __init__(self):
        """Builds a two-order book.

        Returns:
            None: This method returns nothing.
        """
        self.document = {
            'orders': [
                {
                    'order_id': '1001',
                    'status': 'OPEN',
                },
                {
                    'order_id': '1002',
                    'status': 'COMPLETE',
                },
            ],
        }

    def answer(self, query):
        """Answers one request the way the order route does.

        Args:
            query (MultiDict): The query string arguments.

        Returns:
            tuple: A pair of the HTTP status (int) and the JSON body (str).
        """
        try:
            order_filter = OrderBookFilter(query)
        except OrderBookFilterError as error:
            body = {
                'error': str(error),
            }
            return 400, json.dumps(body)
        narrowed = order_filter.apply(self.document, 'orders')
        return 200, json.dumps(narrowed['orders'])

    def run(self):
        """Answers a good request and a bad one, then catches the error as a ValueError.

        Returns:
            None: This method returns nothing.
        """
        good = MultiDict([
            (
                'status',
                'open',
            ),
        ])
        bad = MultiDict([
            (
                'limit',
                'all',
            ),
        ])
        requests = [
            (
                'Good',
                good,
            ),
            (
                'Bad',
                bad,
            ),
        ]
        for label, query in requests:
            status, body = self.answer(query)
            print(f'{label}: {status} {body}')
        print(f'OrderBookFilterError is a ValueError: {issubclass(OrderBookFilterError, ValueError)}')
        try:
            OrderBookFilter(bad)
        except ValueError as error:
            print(f'Caught as ValueError: {type(error).__name__}: {error}')


if __name__ == '__main__':
    AnsweringBadRequestExample().run()
