"""Places an order at a broker the caller names, sends it to a stand-in session, and shows the refusals that stop an order before any broker is asked.

Closing a position has to go to the broker that holds it, so the order names the broker instead of letting the selector choose. `choose_named_broker` still checks that the broker can take the order, and `named_broker_skip_reason` gives the reason when it cannot. `send` sends the prepared order, reads the answer, hands it to the selector with `record_outcome`, and builds the body the API answers with. `attach_daily_count` makes every broker count each request it sends against its daily cap.

Nothing reaches Zerodha: its order class sends through `session`, which the program replaces with a stand-in that records the request and returns the success body recorded in `test_runs/fixtures/order_routes.jsonl`. A stand-in daily count records what it is told. The logins and settings are made-up values, and timing values are left out because they change on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/placement/OrderPlacement/example_2_sending_to_a_named_broker.py
"""

import logging
import time

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.placement import (
    OrderPlacement,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from utilities.configurations import api_configuration


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


class RecordingDailyCount:
    """A stand-in for `DailyOrderCount` that records each request counted.

    Attributes:
        counted (list): The broker names counted, one per request.
    """

    def __init__(self):
        """Builds the count.

        Returns:
            None: This method returns nothing.
        """
        self.counted = []

    def count_sent(self, broker_name):
        """Records one request sent to a broker.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.counted.append(broker_name)

    def release_if_reserved(self):
        """Does nothing, as nothing is reserved here.

        Returns:
            None: This method returns nothing.
        """
        return None


class SendingToANamedBrokerExample:
    """Places a closing sell at Zerodha by name and shows three refusals.

    Attributes:
        placement (OrderPlacement): The placement.
        order (PlaceOrderRequest): The closing order.
        instrument (Instrument): RELIANCE on the NSE.
        login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
        settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.
        session (RecordingSession): The stand-in session Zerodha sends through.
        daily_count (RecordingDailyCount): The stand-in daily count.
    """

    def __init__(self):
        """Configures the placement and puts the stand-ins in place.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = []
        api_configuration['order_excluded_brokers'] = []
        api_configuration['order_warm_brokers'] = []
        self.placement = OrderPlacement(logging.getLogger('example'), 1)
        self.order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'SL-M',
            'trigger_price': '2480',
            'quantity': 10,
        })
        self.instrument = Instrument(
            self.order.instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': {
                    'broker_token': '738561',
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1.0,
                    'tick_size': 0.1,
                },
            },
        )
        self.login_texts = []
        self.settings_texts = []
        for broker_name in self.placement.broker_names:
            if broker_name == 'zerodha':
                self.login_texts.append('{"access_token": "example-zerodha-token"}')
                self.settings_texts.append('{"api_key": "example-api-key"}')
                continue
            self.login_texts.append(None)
            self.settings_texts.append(None)
        success = CannedResponse(
            200,
            {
                'status': 'success',
                'data': {
                    'order_id': '250915000000011',
                },
            },
        )
        self.session = RecordingSession(success)
        self.placement.broker_orders['zerodha'].session = self.session
        self.daily_count = RecordingDailyCount()
        self.placement.attach_daily_count(self.daily_count)

    def run(self):
        """Sends the named order, then shows the refusals.

        Returns:
            None: This method returns nothing.
        """
        print(f'Zerodha skip reason: {self.placement.named_broker_skip_reason(self.order, self.instrument, "zerodha", self.login_texts, self.settings_texts)}')
        print(f'Dhan skip reason: {self.placement.named_broker_skip_reason(self.order, self.instrument, "dhan", self.login_texts, self.settings_texts)}')
        broker_orders, skipped = self.placement.choose_named_broker(self.order, self.instrument, 'zerodha', self.login_texts, self.settings_texts)
        print(f'choose_named_broker: {broker_orders.BROKER_NAME}, skipped {skipped}')
        rotation = self.placement.rotation()
        prepared = self.placement.prepare(self.order, self.instrument, rotation, [], self.login_texts, self.settings_texts, broker_name='zerodha')
        body, status = self.placement.send(prepared, time.perf_counter())
        print(f'Sent: {self.session.sent}')
        print(f'HTTP {status}: outcome {body["outcome"]}, order id {body["order_id"]}, broker response {body["broker_response"]}')
        print(f'Timings reported: {sorted(body["timing_ms"])}')
        print(f'Counted against daily caps: {self.daily_count.counted}')
        self.placement.record_outcome('zerodha', None)
        print('record_outcome accepted a second outcome without complaint')
        try:
            self.placement.choose_named_broker(self.order, self.instrument, 'dhan', self.login_texts, self.settings_texts)
        except RefusedRequestError as error:
            print(f'Named Dhan: HTTP {error.status}, {error.body["error"]}')
        crude = Instrument(
            '22222222-2222-5222-8222-000000000001',
            {
                'segment': 'mcx_commodity_futures',
            },
            {},
            {
                'units_per_lot': None,
                'status': 'conflict',
                'tradeable': False,
            },
        )
        try:
            self.placement.check_contract_size(self.order, crude)
        except RefusedRequestError as error:
            print(f'Untrusted contract: HTTP {error.status}, {error.body["error"]}')
        api_configuration['order_excluded_brokers'] = list(self.placement.broker_names)
        try:
            self.placement.rotation()
        except RefusedRequestError as error:
            print(f'Every broker excluded: HTTP {error.status}, {error.body["error"]}')


if __name__ == '__main__':
    SendingToANamedBrokerExample().run()
