"""Reads the answers a Noren server gives, directly and through a stand-in session, as both Flattrade and Shoonya read them.

A Noren server answers an accepted order with `norenordno`, and a cancel or modification with `result`, which `read_order_id` reads when there is no `norenordno`. Any `stat` other than `Ok` is a refusal, whose message `read_refusal` takes from `emsg` or, failing that, a general message. When a placement meets a server error whose `stat` is `Not_Ok`, `is_settled_refusal` settles it as a refusal. A cancel or modification is decided by simpler rules that never consult it, so the same server error answered to a modification stays `unknown`, as the last answer shows.

The program uses a made-up Noren broker declared on top of `NorenOrders`. Nothing reaches any broker: the order class's `session` is replaced with a stand-in whose `request` method records the URL and returns the next canned answer, in the shapes recorded for Flattrade and Shoonya in `test_runs/fixtures/order_routes.jsonl`. The request is a modification body built by hand, since only the answer matters here.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/noren/NorenOrders/example_2_reading_noren_answers.py
"""

from unified_broker_interface.utilities.broker_orders.noren import NorenOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class ExampleNorenOrders(NorenOrders):
    """A made-up broker on the Noren platform."""

    BROKER_NAME = 'example_noren'
    BASE_URL = 'https://api.example-noren.in/NorenWClientTP'
    ACCOUNT_SETTINGS_FIELD = 'client_code'


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


class ReadingNorenAnswersExample:
    """Reads Noren bodies directly, then decides three modification answers.

    Attributes:
        broker_orders (ExampleNorenOrders): The made-up broker's order class.
    """

    def __init__(self):
        """Builds the order class.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleNorenOrders()

    def run(self):
        """Prints what each reader gives, then sends a modification against three canned answers.

        Returns:
            None: This method returns nothing.
        """
        placed = {
            'stat': 'Ok',
            'norenordno': '26091500000021',
        }
        modified = {
            'stat': 'Ok',
            'result': '26091500000021',
        }
        refused = {
            'stat': 'Not_Ok',
            'emsg': 'Rejected : ORA:Order not found to cancel',
        }
        refused_without_message = {
            'stat': 'Not_Ok',
        }
        print(f'read_order_id of a placement: {self.broker_orders.read_order_id(placed)}')
        print(f'read_order_id of a modification: {self.broker_orders.read_order_id(modified)}')
        print(f'read_refusal of an accepted answer: {self.broker_orders.read_refusal(placed)}')
        print(f'read_refusal of a refusal: {self.broker_orders.read_refusal(refused)}')
        print(f'read_refusal of a refusal with no message: {self.broker_orders.read_refusal(refused_without_message)}')
        print(f'Not_Ok settles a refusal: {self.broker_orders.is_settled_refusal("Not_Ok")}')
        print(f'An empty code settles a refusal: {self.broker_orders.is_settled_refusal("")}')
        broker_request = BrokerRequest(
            'POST',
            f'{ExampleNorenOrders.BASE_URL}/ModifyOrder',
            {},
            data='jData={"norenordno": "26091500000021"}&jKey=example-session-token',
        )
        session = ScriptedSession([
            CannedResponse(200, modified),
            CannedResponse(200, refused),
            CannedResponse(
                502,
                {
                    'stat': 'Not_Ok',
                    'emsg': 'Server busy',
                },
            ),
        ])
        self.broker_orders.session = session
        labels = [
            'accepted',
            'refused inside a success',
            'server error',
        ]
        for label in labels:
            answer = self.broker_orders.send_modify(broker_request)
            print(f'Modify, {label}: {answer.outcome} (HTTP {answer.http_status()}), message {answer.status_message}')
        print(f'Requests the stand-in received: {session.sent}')


if __name__ == '__main__':
    ReadingNorenAnswersExample().run()
