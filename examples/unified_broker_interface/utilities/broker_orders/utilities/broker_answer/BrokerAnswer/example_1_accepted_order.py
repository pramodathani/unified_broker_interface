"""Fills in a `BrokerAnswer` the way a broker order class does after Zerodha accepts an order, and reads it back.

A `BrokerAnswer` starts as `unknown`, holding only the moment the request was sent. The broker order class then records the HTTP status, the decoded body, the order id and the moment the answer came back, and the order route reads three things from it: the body as a dictionary, the HTTP status to answer the caller with, and how long the broker took.

This program writes those fields by hand instead of sending anything. The body is the shape Zerodha's Kite API answers a successful place with, as recorded in `test_runs/fixtures/order_routes.jsonl`. The two clock readings are fixed numbers rather than `time.perf_counter()`, so the timing prints the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/broker_answer/BrokerAnswer/example_1_accepted_order.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)


class AcceptedOrderExample:
    """Builds the answer to an accepted order and prints what the route reads from it.

    Attributes:
        answer (BrokerAnswer): The answer being shown.
    """

    def __init__(self):
        """Builds an answer sent at a fixed moment.

        Returns:
            None: This method returns nothing.
        """
        self.answer = BrokerAnswer(100.0)

    def run(self):
        """Prints the answer before and after the broker's reply is recorded.

        Returns:
            None: This method returns nothing.
        """
        print(f'Before the reply: outcome={self.answer.outcome}, HTTP status for the caller={self.answer.http_status()}')
        print(f'Body fields before the reply: {self.answer.response_fields()}')
        self.answer.answered_at = 100.0425
        self.answer.status_code = 200
        self.answer.response_body = {
            'status': 'success',
            'data': {
                'order_id': '250930000000001',
            },
        }
        self.answer.outcome = 'accepted'
        self.answer.order_id = '250930000000001'
        print(f'Broker HTTP status: {self.answer.status_code}')
        print(f'Body fields: {self.answer.response_fields()}')
        print(f'Order id: {self.answer.order_id}')
        print(f'Outcome: {self.answer.outcome}, HTTP status for the caller: {self.answer.http_status()}')
        print(f'Broker took {self.answer.broker_milliseconds()} ms')


if __name__ == '__main__':
    AcceptedOrderExample().run()
