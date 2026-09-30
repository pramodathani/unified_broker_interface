"""Sends a prepared Zerodha modification to a stand-in session twice: once it is accepted, once the broker fails with a server error.

`PreparedModification.send` sends the modification once, without retrying. A success status means the broker took the instruction (HTTP 200 to the caller). A server error means the broker may or may not have acted on it, so the outcome is `unknown` and the caller gets 504, which tells them to check the order book before trying again.

A modification starts with the stored order's quantity, in the broker's own terms; the route puts the caller's new quantity in with `with_quantities`, as the program does, since an equity's quantity needs no conversion.

Nothing reaches Zerodha. The broker order class sends every request through its `session`, so the program replaces it with a stand-in whose `request` method records the form it was given and returns a canned answer, in the shapes recorded in `test_runs/fixtures/order_routes.jsonl`. Timing values change on every run, so only their names are printed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/prepared_modification/PreparedModification/example_2_accepted_and_unknown.py
"""

import time

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_modification import (
    PreparedModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
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
        sent (list): Each request's method, URL and form.
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
            'data': keyword_arguments['data'],
        })
        return self.response


class AcceptedAndUnknownExample:
    """Sends one prepared modification to two stand-in sessions.

    Attributes:
        broker_orders (ZerodhaOrders): Zerodha's order class.
        prepared (PreparedModification): The prepared modification.
    """

    def __init__(self):
        """Prepares a change of quantity and price for an open LIMIT order.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ZerodhaOrders()
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'variety': 'regular',
            },
        })
        modify_request = ModifyOrderRequest(
            {
                'order_id': '250915000000011',
                'quantity': 20,
                'price': '2501.5',
            },
            werkzeug.datastructures.MultiDict(),
            [
                'zerodha',
            ],
        )
        stored_terms = OrderModification(modify_request, stored_order)
        modification = stored_terms.with_quantities(modify_request.quantity, stored_terms.disclosed_quantity)
        login = {
            'access_token': 'example-access-token',
        }
        settings = {
            'api_key': 'example-api-key',
        }
        broker_request = self.broker_orders.build_modify_request('250915000000011', stored_order, modification, login, settings)
        self.prepared = PreparedModification(self.broker_orders, '250915000000011', stored_order, None, broker_request)

    def send_with(self, label, response):
        """Sends the modification through a stand-in session and prints the answer.

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
        print(f'  timings reported: {sorted(body["timing_ms"])}')

    def run(self):
        """Sends the modification to an accepting and a failing stand-in.

        Returns:
            None: This method returns nothing.
        """
        accepted = CannedResponse(
            200,
            {
                'status': 'success',
                'data': {
                    'order_id': '250915000000011',
                },
            },
        )
        failing = CannedResponse(
            500,
            {
                'message': 'internal error',
            },
        )
        self.send_with('Zerodha accepts', accepted)
        self.send_with('Zerodha fails', failing)


if __name__ == '__main__':
    AcceptedAndUnknownExample().run()
