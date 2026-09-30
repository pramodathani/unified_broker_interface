"""Sends a prepared Dhan cancel to a stand-in session twice, once accepted and once refused, and prints each answer.

`PreparedCancel.send` sends the cancel once, without retrying, and answers with what the broker said: 200 when the broker took the cancel, 422 when it refused it, and 504 when nobody knows. A refusal's message is read from the broker's error fields, here Dhan's `errorMessage`.

Nothing reaches Dhan. The broker order class sends every request through its `session`, so the program replaces that with a stand-in whose `request` method records what it was asked to send and returns a canned answer. The answers are the ones recorded for Dhan in `test_runs/fixtures/order_routes.jsonl`. Timing values change on every run, so only their names are printed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_cancel/PreparedCancel/example_2_sending_to_a_stand_in_dhan.py
"""

import time

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrders
from unified_broker_interface.utilities.broker_orders.utilities.prepared_cancel import (
    PreparedCancel,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class CannedResponse:
    """A stand-in for a `requests.Response` holding a fixed status and JSON body.

    Attributes:
        status_code (int): The HTTP status.
        body (object): The JSON body.
        text (str): The body as text.
    """

    def __init__(self, status_code, body):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            body (object): The JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = str(body)

    def json(self):
        """Returns the JSON body.

        Returns:
            object: The body.
        """
        return self.body


class RecordingSession:
    """A stand-in for `requests.Session` that records each request and answers with a canned response.

    Attributes:
        response (CannedResponse): The answer to every request.
        sent (list): Each request, as a dictionary of method and URL.
    """

    def __init__(self, response):
        """Builds the session.

        Args:
            response (CannedResponse): The answer to every request.

        Returns:
            None: This method returns nothing.
        """
        self.response = response
        self.sent = []

    def request(self, method, url, **keyword_arguments):
        """Records the request and returns the canned response.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments (object): The body, headers, timeout and certificate check.

        Returns:
            CannedResponse: The canned response.
        """
        self.sent.append({
            'method': method,
            'url': url,
            'headers': keyword_arguments['headers'],
        })
        return self.response


class SendingToAStandInDhanExample:
    """Sends one prepared cancel to two stand-in sessions.

    Attributes:
        broker_orders (DhanOrders): Dhan's order class.
        prepared (PreparedCancel): The prepared cancel.
    """

    def __init__(self):
        """Prepares a cancel of an open Dhan order.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = DhanOrders()
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {},
        })
        login = {
            'access_token': 'example-access-token',
        }
        broker_request = self.broker_orders.build_cancel_request('112509150000012', stored_order, login, {})
        self.prepared = PreparedCancel(self.broker_orders, '112509150000012', stored_order, broker_request)

    def send_with(self, label, response):
        """Sends the cancel through a stand-in session and prints the answer.

        Args:
            label (str): What the broker answers.
            response (CannedResponse): The broker's canned answer.

        Returns:
            None: This method returns nothing.
        """
        session = RecordingSession(response)
        self.broker_orders.session = session
        body, status = self.prepared.send(time.perf_counter())
        print(f'{label}:')
        print(f'  sent: {session.sent}')
        print(f'  HTTP {status}, outcome {body["outcome"]}, message {body["status_message"]}')
        print(f'  broker response: {body["broker_response"]}')
        print(f'  timings reported: {sorted(body["timing_ms"])}')

    def run(self):
        """Sends the cancel to an accepting and a refusing stand-in.

        Returns:
            None: This method returns nothing.
        """
        accepted = CannedResponse(
            200,
            {
                'orderId': '112509150000012',
                'orderStatus': 'CANCELLED',
            },
        )
        refused = CannedResponse(
            400,
            {
                'errorType': 'Order_Error',
                'errorCode': 'DH-906',
                'errorMessage': 'Order already traded',
            },
        )
        self.send_with('Dhan accepts', accepted)
        self.send_with('Dhan refuses', refused)


if __name__ == '__main__':
    SendingToAStandInDhanExample().run()
