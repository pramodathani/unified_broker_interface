"""Raises a `FyersRefusal` the way the Fyers socket code does and reads its code and message.

`FyersRefusal` is the exception the Fyers socket code raises when Fyers refuses a request: the symbol-token lookup answering with an error, or the profile check refusing a session. It keeps Fyers' own code, or the HTTP status when there is no code, in `code`, and what Fyers said in `message`, so the reconnect loop can tell a dead session (codes -8, -15, -16, -17 and HTTP 401) from a rate limit (HTTP 429).

This program raises three refusals with the shapes the real code uses and catches each one. It needs no stand-ins, because the exception is plain data.

Notice that `code` keeps its original type, an integer for Fyers codes and HTTP statuses and None when Fyers gave none, and that the exception prints as the pair of its arguments.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersRefusal/example_1_raising_and_catching.py
"""


from stock_brokers.websockets.fyers import (
    FyersRefusal,
)


class RaisingAndCatchingExample:
    """Raises and catches several Fyers refusals.

    Attributes:
        refusals (list): Pairs of a code and a message to raise.
    """

    def __init__(self):
        """Lists the refusals to raise.

        Returns:
            None: This method returns nothing.
        """
        self.refusals = [
            (
                -16,
                'Could not authenticate the user',
            ),
            (
                429,
                'Too many requests',
            ),
            (
                None,
                'no symbol resolved to a topic',
            ),
        ]

    def raise_refusal(self, code, message):
        """Raises one refusal.

        Args:
            code (int | None): Fyers' code, or the HTTP status.
            message (str): What Fyers said.

        Returns:
            None: This method returns nothing.

        Raises:
            FyersRefusal: Always.
        """
        raise FyersRefusal(code, message)

    def run(self):
        """Raises each refusal and prints what the caught exception carries.

        Returns:
            None: This method returns nothing.
        """
        for code, message in self.refusals:
            try:
                self.raise_refusal(code, message)
            except FyersRefusal as refusal:
                print(f'Caught {refusal!r}: code={refusal.code!r} message={refusal.message!r}')


if __name__ == '__main__':
    RaisingAndCatchingExample().run()
