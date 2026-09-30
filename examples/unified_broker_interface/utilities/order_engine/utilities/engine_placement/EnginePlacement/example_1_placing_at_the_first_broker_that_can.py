"""Places one limit order the way the order engine does: read what it needs from Redis, choose a broker, build the request, then send it.

The engine places every leg through `EnginePlacement`. `read_order` rebuilds the validated order from the intent's body, `read_credentials` reads every broker's login and settings in one round trip, `read_instrument` reads the instrument's catalogue entry, and `prepare` combines them to choose a broker and build its request without sending anything. `dry_run_answer` answers with that request, and `send` sends it.

Configuration is set in the program rather than in `.env`: the `fixed_priority` selector with Zerodha preferred before Dhan, no broker excluded and no connection warming. Zerodha has no login in Redis today, so `prepare` passes over it, names the reason in `skipped` and chooses Dhan.

Redis is the in-memory `FakeRedis` from `test_runs/redis_stand_ins.py`, filled with one mapped instrument, Infosys, and the brokers' logins and settings. It counts round trips, which shows that the second read of the same instrument is served from the engine's own instrument cache. Dhan's HTTP session is replaced by `RecordingSession`, which keeps the request it is given and answers the way Dhan's `POST /v2/orders` answers an accepted order, so nothing leaves the machine and no order is placed.

Timings are measured on this machine's clock, so the program prints which timing keys an answer has rather than their values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/EnginePlacement/example_1_placing_at_the_first_broker_that_can.py
"""

import json
import logging
import time

from test_runs.redis_stand_ins import FakeRedis
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from utilities.configurations import api_configuration

MAPPING_DATE = '2026-09-30'
INFOSYS_ID = '6d1f3a52-8b0e-5c47-9a21-3e4f5b6c7d80'


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
    """A stand-in for a broker's `requests.Session` that keeps each request and answers with one recorded response.

    Attributes:
        answer (RecordedResponse): What every request is answered with.
        requests (list): Every request sent, as a dictionary of its method, URL and JSON body.
    """

    def __init__(self, answer):
        """Builds the session.

        Args:
            answer (RecordedResponse): What every request is answered with.

        Returns:
            None: This method returns nothing.
        """
        self.answer = answer
        self.requests = []

    def request(self, method, url, **keyword_arguments):
        """Keeps one request and answers it.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments (object): The other `requests` arguments, such as `json` and `headers`.

        Returns:
            RecordedResponse: The recorded answer.
        """
        self.requests.append({
            'method': method,
            'url': url,
            'json': keyword_arguments.get('json'),
        })
        return self.answer


class PlacingAtTheFirstBrokerThatCanExample:
    """Reads, prepares, dry-runs and sends one Infosys limit order.

    Attributes:
        cache (FakeRedis): The in-memory Redis stand-in.
        placement (EnginePlacement): The placement being shown.
        dhan_session (RecordingSession): The stand-in for Dhan's HTTP session.
        intent (dict): The intent document the engine took off the stream.
    """

    def __init__(self):
        """Sets the configuration, fills Redis and builds the placement with Dhan's session replaced.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = [
            'zerodha',
            'dhan',
        ]
        api_configuration['order_excluded_brokers'] = []
        api_configuration['order_warm_brokers'] = []
        self.cache = FakeRedis()
        self.fill_redis()
        self.placement = EnginePlacement(self.cache, logging.getLogger('example'))
        self.dhan_session = RecordingSession(RecordedResponse(
            200,
            {
                'orderId': '112509300004417',
                'orderStatus': 'PENDING',
            },
        ))
        self.placement.order_placement.broker_orders['dhan'].session = self.dhan_session
        self.intent = {
            'intent_id': '0c9b6a2e4f7d4e1b8a3c5d6e7f801234',
            'instrument_id': INFOSYS_ID,
            'synthetic_type': 'simple',
            'body': {
                'instrument_id': INFOSYS_ID,
                'transaction_type': 'BUY',
                'product': 'CNC',
                'order_type': 'LIMIT',
                'price': 1415.5,
                'quantity': 10,
                'tag': 'swing01',
            },
        }

    def fill_redis(self):
        """Writes the mapping marker, Infosys's catalogue entry and the brokers' logins and settings.

        Returns:
            None: This method returns nothing.
        """
        prefix = f'unified:catalogue:{MAPPING_DATE}:'
        self.cache.strings['unified:catalogue:current_date'] = MAPPING_DATE
        self.cache.strings['unified:catalogue:warm_identifier'] = 'warm-0930-a'
        self.cache.hashes[prefix + 'identity'] = {
            INFOSYS_ID: json.dumps({
                'instrument_id': INFOSYS_ID,
                'exchange': 'nse',
                'segment': 'nse_equities',
                'shape': 'security',
                'symbol': 'INFY',
                'mapping_date': MAPPING_DATE,
            }),
        }
        self.cache.hashes[prefix + 'order_handles'] = {
            INFOSYS_ID: json.dumps({
                'zerodha': {
                    'broker_token': '408065',
                    'order_symbol': 'INFY',
                    'lot_size': 1.0,
                    'tick_size': 0.05,
                },
                'dhan': {
                    'broker_token': '1594',
                    'order_symbol': 'INFY',
                    'lot_size': 1.0,
                    'tick_size': 0.05,
                },
            }),
        }
        self.cache.hashes['last_login'] = {
            'dhan': json.dumps({
                'broker_name': 'dhan',
                'access_token': 'dhan-access-token',
            }),
        }
        self.cache.hashes['settings'] = {
            'dhan': json.dumps({
                'client_id': '1100000001',
            }),
            'zerodha': json.dumps({
                'api_key': 'kite-api-key',
            }),
        }

    def run(self):
        """Walks the order through every step and prints what each one gives.

        Returns:
            None: This method returns nothing.
        """
        order = self.placement.read_order(self.intent)
        print(f'order: {order.transaction_type} {order.quantity} {order.order_type} at {order.price_text}, tag {order.tag}')

        credentials = self.placement.read_credentials()
        mapping_date, warm_identifier, login_texts, settings_texts = credentials
        print(f'mapping date {mapping_date}, warm {warm_identifier}')
        brokers_logged_in = []
        broker_names = self.placement.order_placement.broker_names
        for broker_name, login_text in zip(broker_names, login_texts):
            if self.placement.decode(login_text) is not None:
                brokers_logged_in.append(broker_name)
        print(f'brokers with a login: {brokers_logged_in}')

        before = self.cache.round_trips
        instrument, selector_replies = self.placement.read_instrument(
            order,
            INFOSYS_ID,
            mapping_date,
            warm_identifier,
        )
        print(f'instrument {instrument.identity["symbol"]} on {instrument.segment}, handles for {sorted(instrument.handles)}, selector replies {selector_replies}, round trips {self.cache.round_trips - before}')
        before = self.cache.round_trips
        self.placement.read_instrument(order, INFOSYS_ID, mapping_date, warm_identifier)
        print(f'the same instrument again costs {self.cache.round_trips - before} round trips')

        started_at = time.perf_counter()
        prepared = self.placement.prepare(order, INFOSYS_ID)
        print(f'chosen: {prepared.broker_name}')
        print(f'skipped: {prepared.skipped}')

        dry_body, dry_status = self.placement.dry_run_answer(prepared, started_at)
        print(f'dry run: {dry_status} {json.dumps(dry_body["request"], indent=2)}')
        print(f'requests sent by the dry run: {len(self.dhan_session.requests)}')

        answer_body, status = self.placement.send(prepared, started_at)
        print(f'sent: {status} outcome={answer_body["outcome"]} order_id={answer_body["order_id"]} tag={answer_body["tag"]}')
        print(f'broker_response: {answer_body["broker_response"]}')
        print(f'timing keys: {sorted(answer_body["timing_ms"])}')
        print(f'requests Dhan received: {len(self.dhan_session.requests)}, {self.dhan_session.requests[0]["method"]} {self.dhan_session.requests[0]["url"]}')

        object_text = '{"price": 1415.5}'
        print(f'decode of an object: {self.placement.decode(object_text)}')
        print(f'decode of a list: {self.placement.decode("[1415.5]")}')
        print(f'decode of nothing: {self.placement.decode(None)}')


if __name__ == '__main__':
    PlacingAtTheFirstBrokerThatCanExample().run()
