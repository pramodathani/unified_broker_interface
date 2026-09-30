"""Raises and catches `StoxkartSessionRefused`, the error that marks a dead Stoxkart session.

`StoxkartSessionRefused` is raised when Stoxkart refuses the order socket's authentication because the session is dead: HTTP 401 or a body whose `code` is `AuthorizationError`. The order socket catches it in its loop and logs in again instead of backing off. Its message is Stoxkart's own message, or the HTTP status when Stoxkart gave none.

This program raises it for both kinds of answer, the way the order socket's authentication step decides, and catches it. It needs no stand-ins.

Notice that an answer that is neither is not a refusal.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartSessionRefused/example_1_raising_and_catching.py
"""


from stock_brokers.websockets.stoxkart import (
    StoxkartSessionRefused,
)


class RaisingAndCatchingExample:
    """Checks three authentication answers and catches the refusals.

    Attributes:
        answers (list): Pairs of an HTTP status and a JSON body.
    """

    def __init__(self):
        """Lists the answers to check.

        Returns:
            None: This method returns nothing.
        """
        self.answers = [
            (
                200,
                {
                    'code': 'AuthorizationError',
                    'message': 'Token expired',
                },
            ),
            (
                401,
                {},
            ),
            (
                200,
                {
                    'data': {
                        'RequestId': 'request-1',
                    },
                },
            ),
        ]

    def check(self, status_code, body):
        """Raises a refusal when the answer says the session is dead.

        Args:
            status_code (int): The HTTP status.
            body (dict): The JSON body.

        Returns:
            str: The RequestId when the answer is not a refusal.

        Raises:
            StoxkartSessionRefused: When the answer is HTTP 401 or an `AuthorizationError`.
        """
        if status_code == 401 or body.get('code') == 'AuthorizationError':
            raise StoxkartSessionRefused(body.get('message') or f'HTTP {status_code}')
        return body['data']['RequestId']

    def run(self):
        """Checks each answer and prints the outcome.

        Returns:
            None: This method returns nothing.
        """
        for status_code, body in self.answers:
            try:
                request_id = self.check(status_code, body)
                print(f'HTTP {status_code}: accepted with {request_id}')
            except StoxkartSessionRefused as refusal:
                print(f'HTTP {status_code}: StoxkartSessionRefused: {refusal}')


if __name__ == '__main__':
    RaisingAndCatchingExample().run()
