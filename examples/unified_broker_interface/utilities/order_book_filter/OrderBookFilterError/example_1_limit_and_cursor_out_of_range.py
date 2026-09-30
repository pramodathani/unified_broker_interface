"""Catches the `OrderBookFilterError` raised when `limit` or `cursor` in an order book query cannot be read.

An `OrderBookFilter` reads `limit` and `cursor` as whole numbers when it is built. A `limit` must be from 1 to 10,000 and a `cursor` at least 0, and anything else, including text that is not a number, raises `OrderBookFilterError`. The other filters are plain text and are never refused.

This program builds filters from five query strings, written as Werkzeug `MultiDict` objects like Flask's `request.args`, and prints each error. Nothing touches Redis.

Notice that each message names the parameter and quotes what was given, and that a negative cursor gets the "at least" form of the message, because a cursor has no upper limit.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_book_filter/OrderBookFilterError/example_1_limit_and_cursor_out_of_range.py
"""

from werkzeug.datastructures import MultiDict

from unified_broker_interface.utilities.order_book_filter import (
    OrderBookFilter,
    OrderBookFilterError,
)


class LimitAndCursorOutOfRangeExample:
    """Builds filters from bad query strings and prints each error.

    Attributes:
        queries (list): Pairs of a parameter name and the value given for it.
    """

    def __init__(self):
        """Builds the bad parameters.

        Returns:
            None: This method returns nothing.
        """
        self.queries = [
            (
                'limit',
                'fifty',
            ),
            (
                'limit',
                '0',
            ),
            (
                'limit',
                '20000',
            ),
            (
                'cursor',
                '-5',
            ),
            (
                'cursor',
                '2.5',
            ),
        ]

    def run(self):
        """Builds one filter per bad parameter and prints the error.

        Returns:
            None: This method returns nothing.
        """
        for name, value in self.queries:
            query = MultiDict([
                (
                    name,
                    value,
                ),
            ])
            try:
                OrderBookFilter(query)
            except OrderBookFilterError as error:
                print(f'{name}={value}: {type(error).__name__}: {error}')


if __name__ == '__main__':
    LimitAndCursorOutOfRangeExample().run()
