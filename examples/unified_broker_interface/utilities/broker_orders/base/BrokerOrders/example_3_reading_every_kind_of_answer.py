"""Sends a place request through a stand-in session that answers in every way a broker can, and shows how `BrokerOrders` decides each outcome.

`send_place` sends once and decides: an error status below 500 is `rejected`; a server error is `unknown` unless the broker's code settles it as a refusal; a success status is `rejected` when the body carries a refusal, `accepted` when it carries an order id, and `unknown` otherwise. A connect timeout is `rejected` because nothing left the machine, while a read timeout is `unknown` because the broker may have acted. `send_cancel` and `send_modify` decide by the simpler rules in `decide_instruction_outcome`.

The made-up broker here reads its order id from `data.order_id`, reads a refusal from `status: error`, and treats the error code `OrderException` as settled. Its `session` is replaced with a stand-in whose `request` method returns the next canned answer, or raises the next canned exception, so nothing is sent; the answers are the kinds recorded in `test_runs/fixtures/order_routes.jsonl`. The broker's timing is not printed because it changes on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/base/BrokerOrders/example_3_reading_every_kind_of_answer.py
"""

import requests

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class ExampleBrokerOrders(BrokerOrders):
    """A made-up broker whose answers look like Kite's."""

    BROKER_NAME = 'example_broker'

    def read_order_id(self, response_fields):
        """Reads `data.order_id`.

        Args:
            response_fields (dict): The broker's JSON body.

        Returns:
            object: The order id, or None.
        """
        data = response_fields.get('data')
        if isinstance(data, dict):
            return data.get('order_id')
        return None

    def read_refusal(self, response_fields):
        """Reads the message of a body whose status is `error`.

        Args:
            response_fields (dict): The broker's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        if response_fields.get('status') == 'error':
            return response_fields.get('message')
        return None

    def is_settled_refusal(self, error_code):
        """Whether the error code is `OrderException`.

        Args:
            error_code (str): The code read from the error answer.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code == 'OrderException'


class CannedResponse:
    """A stand-in for a `requests.Response`.

    Attributes:
        status_code (int): The HTTP status.
        body (object): The JSON body, or None when the body is not JSON.
        text (str): The body as text.
    """

    def __init__(self, status_code, body, text=None):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            body (object): The JSON body, or None when the body is not JSON.
            text (str | None): The body as text, or None to use the JSON body's text.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = text or str(body)

    def json(self):
        """Returns the JSON body.

        Returns:
            object: The body.

        Raises:
            ValueError: When the body is not JSON.
        """
        if self.body is None:
            raise ValueError('not JSON')
        return self.body


class ScriptedSession:
    """A stand-in for `requests.Session` that answers each request with the next scripted answer.

    Attributes:
        script (list): The answers, each a `CannedResponse` or an exception to raise.
        requests_seen (int): How many requests arrived.
    """

    def __init__(self, script):
        """Builds the session.

        Args:
            script (list): The answers, in order.

        Returns:
            None: This method returns nothing.
        """
        self.script = script
        self.requests_seen = 0

    def request(self, method, url, **keyword_arguments):
        """Returns or raises the next scripted answer.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments (object): The body, headers, timeout and certificate check.

        Returns:
            CannedResponse: The next answer.

        Raises:
            requests.exceptions.RequestException: When the next answer is an exception.
        """
        answer = self.script[self.requests_seen]
        self.requests_seen = self.requests_seen + 1
        if isinstance(answer, Exception):
            raise answer
        return answer


class ReadingEveryKindOfAnswerExample:
    """Sends one request per scripted answer and prints each outcome.

    Attributes:
        broker_orders (ExampleBrokerOrders): The broker's order class.
        broker_request (BrokerRequest): The request sent every time.
    """

    def __init__(self):
        """Builds the order class and the request.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleBrokerOrders()
        self.broker_request = BrokerRequest(
            'POST',
            'https://api.example-broker.in/orders/regular',
            {
                'Authorization': 'token example',
            },
            data={
                'tradingsymbol': 'RELIANCE',
                'quantity': 10,
            },
        )

    def show(self, label, answer):
        """Prints one answer's outcome.

        Args:
            label (str): What the broker answered.
            answer (BrokerAnswer): The decided answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}: {answer.outcome} (HTTP {answer.http_status()}), order id {answer.order_id}, message {answer.status_message}')

    def run(self):
        """Sends the request against each scripted answer.

        Returns:
            None: This method returns nothing.
        """
        place_script = [
            (
                'Accepted',
                CannedResponse(
                    200,
                    {
                        'status': 'success',
                        'data': {
                            'order_id': '250915000000011',
                        },
                    },
                ),
            ),
            (
                'Refusal inside a success',
                CannedResponse(
                    200,
                    {
                        'status': 'error',
                        'message': 'Markets are closed right now.',
                    },
                ),
            ),
            (
                'Success without an order id',
                CannedResponse(200, {}),
            ),
            (
                'Client error',
                CannedResponse(
                    400,
                    {
                        'message': 'bad request',
                    },
                ),
            ),
            (
                'Settled server error',
                CannedResponse(
                    500,
                    {
                        'status': 'error',
                        'error_type': 'OrderException',
                        'message': 'Order could not be placed',
                    },
                ),
            ),
            (
                'Plain server error',
                CannedResponse(503, None, 'Service Unavailable'),
            ),
            (
                'Connect timeout',
                requests.exceptions.ConnectTimeout('connect timed out'),
            ),
            (
                'Read timeout',
                requests.exceptions.ReadTimeout('read timed out'),
            ),
        ]
        answers = []
        for label, answer in place_script:
            answers.append(answer)
        self.broker_orders.session = ScriptedSession(answers)
        for label, answer in place_script:
            self.show(f'Place, {label}', self.broker_orders.send_place(self.broker_request))
        settled = CannedResponse(
            500,
            {
                'error_type': 'OrderException',
                'message': 'Order could not be placed',
            },
        )
        print(f'Error code of the settled answer: {self.broker_orders.error_code(settled.body)}')
        nested = BrokerAnswer(0.0)
        nested.response_body = {
            'error': {
                'code': 'GA001',
                'message': 'nested failure',
            },
        }
        print(f'Nested error: code {self.broker_orders.error_code(nested.response_fields())}, message {self.broker_orders.error_message(nested)}')
        print(f'Order id read from a body: {self.broker_orders.read_order_id(place_script[0][1].body)}')
        print(f'Refusal read from a body: {self.broker_orders.read_refusal(place_script[1][1].body)}')
        print(f'OrderException settles a refusal: {self.broker_orders.is_settled_refusal("OrderException")}')
        instruction_script = [
            CannedResponse(
                200,
                {
                    'status': 'success',
                },
            ),
            CannedResponse(
                500,
                {
                    'message': 'internal error',
                },
            ),
        ]
        self.broker_orders.session = ScriptedSession(instruction_script)
        self.show('Cancel, success', self.broker_orders.send_cancel(self.broker_request))
        self.show('Modify, server error', self.broker_orders.send_modify(self.broker_request))
        self.broker_orders.session = ScriptedSession([
            CannedResponse(
                404,
                {
                    'message': 'order not found',
                },
            ),
        ])
        raw_answer = self.broker_orders.send(self.broker_request)
        print(f'send alone leaves the outcome {raw_answer.outcome} with HTTP {raw_answer.status_code}')
        self.broker_orders.decide_instruction_outcome(raw_answer)
        self.show('After decide_instruction_outcome', raw_answer)
        self.broker_orders.count_message(raw_answer)
        print('count_message counted nothing, as no daily count is attached')


if __name__ == '__main__':
    ReadingEveryKindOfAnswerExample().run()
