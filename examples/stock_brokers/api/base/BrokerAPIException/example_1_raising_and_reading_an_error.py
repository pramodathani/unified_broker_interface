"""Raises a `BrokerAPIException` and reads the code and message it carries.

`BrokerAPIException` is what every broker class raises, through its own subclass, when a broker refuses a request. It holds the broker's error `code` and a `message`, both optional, and passes both to `Exception` as well, so they also appear in `args` and in the exception's text.

This program raises one with a Kite-style code and message, as `ZerodhaAPI` does for an expired token, and one with neither, and prints what a handler can read from each. It needs no data store, no network and no broker.

Notice that the code and message are plain attributes, and that an exception raised without them still has both, set to None.

Run it from the project root:

    python examples/stock_brokers/api/base/BrokerAPIException/example_1_raising_and_reading_an_error.py
"""

from stock_brokers.api.base import (
    BrokerAPIException,
)


class RaisingAndReadingAnErrorExample:
    """Raises two exceptions and prints what each holds.

    Attributes:
        errors (list): The exceptions to raise, one with a code and message and one without.
    """

    def __init__(self):
        """Builds the exceptions to raise.

        Returns:
            None: This method returns nothing.
        """
        self.errors = [
            BrokerAPIException(code='TokenException', message='Incorrect `api_key` or `access_token`.'),
            BrokerAPIException(),
        ]

    def run(self):
        """Raises each exception, catches it and prints its fields.

        Returns:
            None: This method returns nothing.
        """
        for error_to_raise in self.errors:
            try:
                raise error_to_raise
            except BrokerAPIException as error:
                print(f'code: {error.code!r}')
                print(f'message: {error.message!r}')
                print(f'args: {error.args!r}')
                print(f'text: {error}')
                print()


if __name__ == '__main__':
    RaisingAndReadingAnErrorExample().run()
