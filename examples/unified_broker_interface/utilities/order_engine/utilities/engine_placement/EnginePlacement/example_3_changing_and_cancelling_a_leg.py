"""Changes and then cancels one order the engine placed at Zerodha, and shows the refusals that stop a change before it is sent.

An order type changes a resting leg through `modify_leg`, for example to reduce the other leg of a linked pair or to move a stop to breakeven, and takes it off the book through `cancel`. Both read the broker's login and settings through `read_credentials_for`, and both build the request from the order as the broker's own order book in Redis holds it, read through `stored_order`, because values such as Zerodha's `variety` exist only there.

The program first reads Zerodha's credentials and the stored order, then changes the leg's quantity and price, and cancels it. It then asks for three things that are refused before anything is sent: a modification that changes nothing, which is refused with HTTP 400; a cancel of an order the order book does not hold, which is looked for again every tenth of a second and refused with HTTP 404 once the wait runs out; and credentials for a broker the engine does not know, which is refused with HTTP 503.

Redis is the in-memory `FakeRedis` from `test_runs/redis_stand_ins.py`, holding Zerodha's login, its settings and one open order in `zerodha:orders:orders`. Zerodha's HTTP session is replaced by `RecordingSession`, which keeps each request and answers the way Kite answers an accepted change or cancel, so no order is touched. The wait for a missing order is shortened to a fifth of a second so the program finishes quickly.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/EnginePlacement/example_3_changing_and_cancelling_a_leg.py
"""

import decimal
import json
import logging

from test_runs.redis_stand_ins import FakeRedis
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from utilities.configurations import api_configuration

ORDER_ID = '250930000000417'


class RecordedResponse:
    """A stand-in for a `requests` response holding a JSON body.

    Attributes:
        status_code (int): The HTTP status.
        body (dict): The JSON body.
        text (str): The body as text.
    """

    def __init__(self, status_code, body):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            body (dict): The JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        """The body decoded as JSON.

        Returns:
            dict: The body.
        """
        return self.body


class RecordingSession:
    """A stand-in for Zerodha's `requests.Session` that keeps each request and answers as Kite answers an accepted instruction.

    Attributes:
        requests (list): Every request sent, as a dictionary of its method, URL and form.
    """

    def __init__(self):
        """Builds the session with no requests kept.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def request(self, method, url, **keyword_arguments):
        """Keeps one request and answers it.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments (object): The other `requests` arguments, such as `data` and `headers`.

        Returns:
            RecordedResponse: Kite's success answer naming the order.
        """
        self.requests.append({
            'method': method,
            'url': url,
            'form': keyword_arguments.get('data'),
        })
        return RecordedResponse(
            200,
            {
                'status': 'success',
                'data': {
                    'order_id': ORDER_ID,
                },
            },
        )


class ChangingAndCancellingALegExample:
    """Modifies and cancels one Zerodha order, then shows three refusals.

    Attributes:
        cache (FakeRedis): The in-memory Redis stand-in.
        placement (EnginePlacement): The placement being shown.
        zerodha_session (RecordingSession): The stand-in for Zerodha's HTTP session.
    """

    def __init__(self):
        """Sets the configuration, fills Redis and builds the placement with Zerodha's session replaced.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_warm_brokers'] = []
        self.cache = FakeRedis()
        self.cache.hashes['last_login'] = {
            'zerodha': json.dumps({
                'broker_name': 'zerodha',
                'access_token': 'zerodha-access-token',
            }),
        }
        self.cache.hashes['settings'] = {
            'zerodha': json.dumps({
                'api_key': 'kite-api-key',
            }),
        }
        self.cache.hashes['zerodha:orders:orders'] = {
            ORDER_ID: json.dumps({
                'order': {
                    'status': 'OPEN',
                    'order_id': ORDER_ID,
                    'instrument_token': '408065',
                    'tradingsymbol': 'INFY',
                    'exchange': 'NSE',
                    'transaction_type': 'BUY',
                    'product': 'MIS',
                    'order_type': 'LIMIT',
                    'validity': 'DAY',
                    'quantity': 20,
                    'filled_quantity': 0,
                    'pending_quantity': 20,
                    'disclosed_quantity': 0,
                    'price': 1415.5,
                    'trigger_price': 0.0,
                    'tag': 'pair01',
                },
                'data': {
                    'variety': 'regular',
                    'order_id': ORDER_ID,
                },
            }),
        }
        self.placement = EnginePlacement(self.cache, logging.getLogger('example'))
        self.zerodha_session = RecordingSession()
        self.placement.order_placement.broker_orders['zerodha'].session = self.zerodha_session

    def run(self):
        """Reads, modifies and cancels the order, then asks for the three refused things.

        Returns:
            None: This method returns nothing.
        """
        broker_orders, login, settings = self.placement.read_credentials_for('zerodha')
        print(f'credentials for {broker_orders.BROKER_NAME}: login has access_token {bool(login.get("access_token"))}, settings {sorted(settings)}')

        stored = self.placement.stored_order('zerodha', ORDER_ID)
        print(f'stored order: {stored.status}, variety {stored.data["variety"]}, quantity {stored.order["quantity"]} at {stored.order["price"]}')

        modified = self.placement.modify_leg(
            'zerodha',
            ORDER_ID,
            quantity=12,
            price=decimal.Decimal('1414.00'),
        )
        print(f'modify: {modified.outcome}, HTTP {modified.status_code}')
        print(f'  sent {self.zerodha_session.requests[0]}')

        cancelled = self.placement.cancel('zerodha', ORDER_ID)
        print(f'cancel: {cancelled.outcome}, HTTP {cancelled.status_code}')
        print(f'  sent {self.zerodha_session.requests[1]}')

        try:
            self.placement.modify_leg('zerodha', ORDER_ID)
        except RefusedRequestError as refusal:
            print(f'modify with nothing to change: {refusal.status} {refusal.body["error"]}')

        self.placement.stored_order_wait_seconds = 0.2
        try:
            self.placement.cancel('zerodha', '250930000009999')
        except RefusedRequestError as refusal:
            print(f'cancel of an order the book lacks: {refusal.status} {refusal.body["error"]}')

        try:
            self.placement.read_credentials_for('sharekhan')
        except RefusedRequestError as refusal:
            print(f'credentials for an unknown broker: {refusal.status} {refusal.body["error"]}')

        print(f'requests Zerodha received in all: {len(self.zerodha_session.requests)}')


if __name__ == '__main__':
    ChangingAndCancellingALegExample().run()
