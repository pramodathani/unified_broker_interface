"""Raises and catches `GrowwSocketRefused`, the error that marks a dead Groww access token.

`GrowwSocketRefused` is raised when Groww refuses a socket token request with HTTP 401 or 403, which means the access token is dead. Both Groww sockets catch it in their connect step and turn it into a refused login, so their reconnect loops log in again. It is a plain `Exception` subclass whose message says the HTTP status and the start of Groww's answer.

This program raises it with the message shape the real code uses and catches it, both as itself and as a plain `Exception`. It needs no stand-ins.

Notice that the class name is what tells a refused login apart from any other failure.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwSocketRefused/example_1_raising_and_catching.py
"""


from stock_brokers.websockets.groww import (
    GrowwSocketRefused,
)


class RaisingAndCatchingExample:
    """Raises and catches a Groww socket refusal.

    Attributes:
        message (str): The message the refusal carries.
    """

    def __init__(self):
        """Builds the message the way the session does.

        Returns:
            None: This method returns nothing.
        """
        self.message = 'HTTP 403: {"message": "Forbidden"}'

    def refuse(self):
        """Raises the refusal.

        Returns:
            None: This method returns nothing.

        Raises:
            GrowwSocketRefused: Always.
        """
        raise GrowwSocketRefused(self.message)

    def run(self):
        """Catches the refusal twice, once by its own class and once as any exception.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.refuse()
        except GrowwSocketRefused as refusal:
            print(f'Caught as a refused login: {refusal}')
        try:
            self.refuse()
        except Exception as error:
            print(f'Caught as {type(error).__name__}, a subclass of Exception: {isinstance(error, Exception)}')


if __name__ == '__main__':
    RaisingAndCatchingExample().run()
