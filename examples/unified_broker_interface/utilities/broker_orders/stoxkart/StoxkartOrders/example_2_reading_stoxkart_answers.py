"""Sends Stoxkart's place and cancel requests to a stand-in session that answers the way Stoxkart does, and shows how each answer is decided.

Stoxkart answers an accepted order with `data.order_id`, and `read_order_id` also reads an `order_id` at the top of a body with no `data`. `StoxkartOrders` reads no refusal from a success status and settles no server error, so Stoxkart's own refusal, a 200 with `status: error` such as the market-closed answer, is decided `unknown` for a place and `accepted` for a cancel, exactly as the recorded fixtures show.

Nothing reaches Stoxkart. Its order class sends every request through its `session`, so the program replaces that with a stand-in whose `request` method records the method and URL and returns the next canned answer. The answers are the ones recorded for Stoxkart in `test_runs/fixtures/order_routes.jsonl`, and the login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/stoxkart/StoxkartOrders/example_2_reading_stoxkart_answers.py
"""

from unified_broker_interface.utilities.broker_orders.stoxkart import (
    StoxkartOrders,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class CannedResponse:
    """A stand-in for a `requests.Response` holding a fixed status and body.

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
    """A stand-in for `requests.Session` that records each request and answers with the next canned response.

    Attributes:
        script (list): The canned responses, in order.
        sent (list): Each request's method and URL, as text.
    """

    def __init__(self, script):
        """Builds the session.

        Args:
            script (list): The canned responses, in order.

        Returns:
            None: This method returns nothing.
        """
        self.script = script
        self.sent = []

    def request(self, method, url, **keyword_arguments):
        """Records the request and returns the next canned response.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments (object): The body, headers, timeout and certificate check.

        Returns:
            CannedResponse: The next canned response.
        """
        self.sent.append(f'{method} {url}')
        return self.script[len(self.sent) - 1]


class ReadingStoxkartAnswersExample:
    """Decides several canned Stoxkart answers and reads bodies directly.

    Attributes:
        broker_orders (StoxkartOrders): The broker's order class.
        place_request (BrokerRequest): The place request sent against each answer.
        cancel_request (BrokerRequest): The cancel request sent against each answer.
    """

    def __init__(self):
        """Builds the order class and the place and cancel requests, which are only ever sent to the stand-in session.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = StoxkartOrders()
        order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        })
        handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE-EQ',
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        instrument = Instrument(
            order.instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'stoxkart': handle,
            },
        )
        login = {
            'access_token': 'example-stoxkart-token',
        }
        settings = {
            'ucc_code': 'SX00001',
            'api_key': 'example-api-key',
        }
        self.place_request = self.broker_orders.build_place_request(order, instrument, handle, login, settings)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {
                'variety': 'NORMAL',
            },
        })
        self.cancel_request = self.broker_orders.build_cancel_request('SX0001', stored_order, login, settings)

    def show(self, label, answer):
        """Prints one decided answer.

        Args:
            label (str): What the broker answered.
            answer (BrokerAnswer): The decided answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}: {answer.outcome} (HTTP {answer.http_status()}), order id {answer.order_id}, message {answer.status_message}')

    def run(self):
        """Sends the place request against each canned place answer and the cancel request against each canned cancel answer, then reads bodies directly.

        Returns:
            None: This method returns nothing.
        """
        place_answers = [
            (
                'accepted',
                CannedResponse(
                    200,
                    {
                        'status': 'success',
                        'message': 'Order Submitted',
                        'data': {
                            'order_id': 'SX0001',
                        },
                    },
                ),
            ),
            (
                'refusal inside a success',
                CannedResponse(
                    200,
                    {
                        'status': 'error',
                        'message': 'MARKET IS CLOSE YOU CANNOT PLACE AN ORDER NOW',
                    },
                ),
            ),
            (
                'server error',
                CannedResponse(
                    500,
                    {
                        'status': 'error',
                        'message': 'upstream failure',
                    },
                ),
            ),
        ]
        cancel_answers = [
            (
                'accepted',
                CannedResponse(
                    200,
                    {
                        'status': 'success',
                        'message': 'Order Cancelled',
                        'data': {
                            'order_id': 'SX0001',
                        },
                    },
                ),
            ),
            (
                'refusal inside a success',
                CannedResponse(
                    200,
                    {
                        'status': 'error',
                        'message': 'order not found',
                    },
                ),
            ),
        ]
        responses = []
        for label, response in place_answers:
            responses.append(response)
        for label, response in cancel_answers:
            responses.append(response)
        session = ScriptedSession(responses)
        self.broker_orders.session = session
        for label, response in place_answers:
            self.show(f'Place, {label}', self.broker_orders.send_place(self.place_request))
        for label, response in cancel_answers:
            self.show(f'Cancel, {label}', self.broker_orders.send_cancel(self.cancel_request))
        print(f'Requests the stand-in received: {session.sent}')
        print(f'read_order_id of the accepted body: {self.broker_orders.read_order_id(place_answers[0][1].body)}')
        top_level = {
            'order_id': 'SX0002',
        }
        print(f'read_order_id of a body with no data: {self.broker_orders.read_order_id(top_level)}')


if __name__ == '__main__':
    ReadingStoxkartAnswersExample().run()
