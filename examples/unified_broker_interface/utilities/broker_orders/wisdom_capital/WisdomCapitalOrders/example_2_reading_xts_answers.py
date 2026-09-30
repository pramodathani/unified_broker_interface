"""Sends Wisdom Capital's place and cancel requests to a stand-in session that answers the way its XTS server does, and shows how each answer is decided.

XTS answers an accepted order with `result.AppOrderID`, a number, which is read as text. It refuses with a `type` other than `success`, whose `description` `read_refusal` reads. On a server error, a code starting with `e-orders`, `e-order` or `e-rms` is a settled refusal, which `is_settled_refusal` decides.

Nothing reaches Wisdom Capital. Its order class sends every request through its `session`, so the program replaces that with a stand-in whose `request` method records the method and URL and returns the next canned answer. The answers are the ones recorded for Wisdom Capital in `test_runs/fixtures/order_routes.jsonl`, and the login and settings are made-up values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/wisdom_capital/WisdomCapitalOrders/example_2_reading_xts_answers.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.broker_orders.wisdom_capital import (
    WisdomCapitalOrders,
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


class ReadingXtsAnswersExample:
    """Decides several canned XTS answers and reads bodies directly.

    Attributes:
        broker_orders (WisdomCapitalOrders): The broker's order class.
        place_request (BrokerRequest): The place request sent against each answer.
        cancel_request (BrokerRequest): The cancel request sent against each answer.
    """

    def __init__(self):
        """Builds the order class and the place and cancel requests, which are only ever sent to the stand-in session.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = WisdomCapitalOrders()
        order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        })
        handle = {
            'broker_token': '2885',
            'order_symbol': None,
            'lot_size': 1.0,
            'tick_size': 0.05,
        }
        instrument = Instrument(
            order.instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'wisdom_capital': handle,
            },
        )
        login = {
            'access_token': 'example-xts-token',
        }
        settings = {
            'ucc_code': 'WC00001',
        }
        self.place_request = self.broker_orders.build_place_request(order, instrument, handle, login, settings)
        stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {
                'OrderUniqueIdentifier': 'T1',
            },
        })
        self.cancel_request = self.broker_orders.build_cancel_request('1234567890', stored_order, login, settings)

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
                        'type': 'success',
                        'result': {
                            'AppOrderID': 1234567890,
                        },
                    },
                ),
            ),
            (
                'refusal inside a success',
                CannedResponse(
                    200,
                    {
                        'type': 'error',
                        'code': 'e-orders-0005',
                        'description': 'Order rejected',
                    },
                ),
            ),
            (
                'settled server error',
                CannedResponse(
                    500,
                    {
                        'type': 'error',
                        'code': 'e-rms-0001',
                        'description': 'RMS rejected',
                    },
                ),
            ),
            (
                'plain server error',
                CannedResponse(
                    500,
                    {
                        'type': 'error',
                        'code': 'e-session-0002',
                        'description': 'Internal error',
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
                        'type': 'success',
                        'result': {
                            'AppOrderID': 1234567890,
                        },
                    },
                ),
            ),
            (
                'refusal inside a success',
                CannedResponse(
                    200,
                    {
                        'type': 'error',
                        'description': 'Order not found',
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
        print(f'read_order_id of the accepted body: {self.broker_orders.read_order_id(place_answers[0][1].body)!r}')
        print(f'read_refusal of the refused body: {self.broker_orders.read_refusal(place_answers[1][1].body)}')
        bare_error = {
            'type': 'error',
        }
        print(f'read_refusal of an error with no description: {self.broker_orders.read_refusal(bare_error)}')
        error_codes = [
            'E-ORDER-0010',
            'e-session-0002',
        ]
        for error_code in error_codes:
            print(f'{error_code} settles a refusal: {self.broker_orders.is_settled_refusal(error_code)}')


if __name__ == '__main__':
    ReadingXtsAnswersExample().run()
