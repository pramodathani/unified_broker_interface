"""Shows a `BrokerAnswer` whose body is not JSON, and the HTTP status the route answers with for each outcome.

Some brokers answer an overloaded gateway with an HTML page rather than JSON. The broker order class then keeps the first 300 characters of the text as `response_body`, and `response_fields` gives an empty dictionary so the code reading error codes never has to check the type first.

The program also walks the three outcomes through `http_status`: `accepted` is answered with 200, `rejected` with 422 and `unknown` with 504, the last because the broker may or may not have acted on the order. The clock readings are fixed numbers, so the timing is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/broker_answer/BrokerAnswer/example_2_text_body_and_every_outcome.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)


class TextBodyAndEveryOutcomeExample:
    """Records a gateway error page in an answer and prints every outcome's HTTP status.

    Attributes:
        answer (BrokerAnswer): The answer being shown.
    """

    def __init__(self):
        """Builds an answer sent at a fixed moment.

        Returns:
            None: This method returns nothing.
        """
        self.answer = BrokerAnswer(5.0)

    def run(self):
        """Prints what the route reads from a text answer, then each outcome's status.

        Returns:
            None: This method returns nothing.
        """
        self.answer.answered_at = 7.5
        self.answer.status_code = 502
        self.answer.response_body = '<html><body>502 Bad Gateway</body></html>'
        self.answer.status_message = self.answer.response_body
        print(f'Broker HTTP status: {self.answer.status_code}')
        print(f'Body kept as text: {self.answer.response_body}')
        print(f'Body fields: {self.answer.response_fields()}')
        print(f'Broker took {self.answer.broker_milliseconds()} ms')
        outcomes = [
            'accepted',
            'rejected',
            'unknown',
        ]
        for outcome in outcomes:
            self.answer.outcome = outcome
            print(f'Outcome {outcome} is answered with HTTP {self.answer.http_status()}')


if __name__ == '__main__':
    TextBodyAndEveryOutcomeExample().run()
