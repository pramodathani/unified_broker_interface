"""Builds, raises and catches the refusal the order routes answer with when no broker can take an order.

`RefusedRequestError.refusal` builds the error from a message, an HTTP status and any extra fields for the answer's body. The route raises it deep inside its checks and catches it at the top, where it turns `body` and `status` straight into the HTTP answer. No broker is called along the way.

The extra field here is `skipped`, the list of brokers passed over and why, which is what the place route answers with when every broker refuses an order before anything is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/refused_request/RefusedRequestError/example_1_refusing_before_any_broker.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class RefusingBeforeAnyBrokerExample:
    """Raises a refusal listing the brokers passed over and prints the answer it becomes.

    Attributes:
        skipped (list): The brokers passed over, each with a reason.
    """

    def __init__(self):
        """Lists two brokers that could not take the order.

        Returns:
            None: This method returns nothing.
        """
        self.skipped = [
            {
                'broker': 'zerodha',
                'reason': 'has no login in Redis',
            },
            {
                'broker': 'dhan',
                'reason': 'has no mapping for the instrument',
            },
        ]

    def choose_broker(self):
        """Pretends to choose a broker and refuses because none is left.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: Always, because every broker was passed over.
        """
        raise RefusedRequestError.refusal(
            'no broker can take the order',
            503,
            skipped=self.skipped,
        )

    def run(self):
        """Catches the refusal and prints its status, message and body.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.choose_broker()
        except RefusedRequestError as error:
            print(f'HTTP status: {error.status}')
            print(f'Message: {error}')
            print(f'Body: {error.body}')


if __name__ == '__main__':
    RefusingBeforeAnyBrokerExample().run()
