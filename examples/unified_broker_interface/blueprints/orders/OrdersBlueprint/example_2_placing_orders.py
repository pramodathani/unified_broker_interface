"""Places orders through `POST /api/orders/place`: one order, a list of orders, and the checks an order passes before it is handed to the order engine.

The place route never talks to a broker itself. It checks the access token and the body, finds the instrument the order names, by `instrument_id` or by `exchange`, `segment` and identity fields, and writes the order for the order engine, `bin/unified/orders/order_engine`, which chooses the broker, sends the order and writes back the answer the route is waiting for. An order named by identity fields is looked up in the day's catalogue once, and this worker then remembers the answer. A list of orders is written for the engine in one step and answered entry by entry.

This program uses the in-memory Redis stand-in and the recorded catalogue of the offline order route suite, `test_runs/order_routes.py`, and runs the real order engine on the same thread whenever the route waits for it, from `test_runs/engine_stand_ins.py`. The broker network is a stub that answers every request with Zerodha's success body and records it, `uuid.uuid4` counts up so that intent ids are the same on every run, and the broker selector is set to send every order to Zerodha first. Nothing leaves the process.

Notice in the output that `resolve_instrument_id` finds RELIANCE without a single Redis round trip, because the dry run before it already looked RELIANCE up and this worker kept the answer, and that a list refuses each bad entry on its own while the good one is still placed.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_2_placing_orders.py
"""

import json
import time
import uuid

import flask
import requests

from test_runs import engine_stand_ins
from test_runs import redis_stand_ins
from test_runs.order_routes import (
    API_TOKEN,
    FakeBrokerNetwork,
    OrderRoutesAnswers,
    OrderRoutesState,
)
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints.orders import (
    OrdersBlueprint,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from utilities.configurations import api_configuration

MAPPING_DATE = '2026-09-15'
WARM_IDENTIFIER = 'warm-one'
RELIANCE = OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']


class PlacingOrdersExample:
    """Places a single order and a list, reads one answer back, and shows each check the route makes.

    Attributes:
        cache (redis_stand_ins.InlineEngineRedis): The stand-in Redis client the blueprint and the order engine share.
        network (FakeBrokerNetwork): The stub every broker request goes to.
        blueprint (OrdersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint and has the stub network accept every order as Zerodha does.

        Returns:
            None: This method returns nothing.
        """
        self.cache = None
        self.network = None
        self.blueprint = None
        self.application = None
        self.build_blueprint()
        self.network.reset({
            'status': 200,
            'json': OrderRoutesAnswers().place_success('zerodha'),
        })

    def stand_in_cache(self):
        """Hands a newly built blueprint the stand-in instead of a Redis client.

        Returns:
            redis_stand_ins.InlineEngineRedis: The stand-in.
        """
        return self.cache

    def stand_in_mongo_database(self):
        """Hands a newly built blueprint no MongoDB database, since the order routes never read it.

        Returns:
            None: Always None.
        """
        return None

    def build_blueprint(self):
        """Fills the stand-in Redis, points the broker network at the stand-in, and builds the blueprint.

        The blueprint opens its stores through `get_cache` and `get_mongo_db` while it is built, and hands the Redis client on to the objects it builds, so those two functions are pointed at the stand-ins first. Configuration is set so that orders go to Zerodha first, no broker is excluded, no connection is warmed, and at most ten orders a second go to each broker.

        Returns:
            None: This method returns nothing.
        """
        starting_state = OrderRoutesState().build()
        self.cache = redis_stand_ins.InlineEngineRedis()
        self.cache.strings = starting_state.strings
        self.cache.hashes = starting_state.hashes
        self.cache.sorted_sets = starting_state.sorted_sets
        self.cache.strings[ENGINE_LOCK_KEY] = 'engine-process'
        self.network = FakeBrokerNetwork()
        requests.Session.request = self.network.request
        uuid.uuid4 = engine_stand_ins.CountingUuid()
        api_configuration['order_warm_brokers'] = [
            '',
        ]
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = [
            'zerodha',
        ]
        api_configuration['order_rate_per_second'] = 0
        api_configuration['order_rate_per_broker_per_second'] = 10
        api_configuration['order_rate_wait_seconds'] = 1
        api_configuration['order_hold_limits'] = False
        blueprint_base.get_cache = self.stand_in_cache
        blueprint_base.get_mongo_db = self.stand_in_mongo_database
        self.blueprint = OrdersBlueprint()
        self.cache.inline_engine = engine_stand_ins.InlineEngine(self.cache)
        self.application = flask.Flask('orders_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/orders',
        )

    def request(self, method, route, body=None, query=None):
        """Opens the request context a request to one route runs in, carrying the right token.

        Args:
            method (str): The HTTP method.
            route (str): The route under `/api/orders/`.
            body (dict | None): The JSON body, or None to send none.
            query (dict | None): The query string parameters.

        Returns:
            flask.ctx.RequestContext: The context, to enter with `with` around the handler call.
        """
        return self.application.test_request_context(
            f'/api/orders/{route}',
            method=method,
            json=body,
            query_string=query,
            headers={
                'access-token': API_TOKEN,
            },
        )

    def shown(self, body):
        """Turns an answer's body into one line of JSON, leaving out `timing_ms`, which changes on every run.

        Args:
            body (object): The answer's body.

        Returns:
            str: The body as sorted JSON.
        """
        if isinstance(body, dict):
            body = dict(body)
            body.pop('timing_ms', None)
        return json.dumps(body, sort_keys=True)

    def show(self, title, answer):
        """Prints the status and body of a handler's Flask answer.

        Args:
            title (str): What the answer is for.
            answer (tuple): The Flask JSON response (flask.Response) and its HTTP status (int).

        Returns:
            None: This method returns nothing.
        """
        response, status = answer
        print(f'{title}: {status} {self.shown(response.get_json())}')

    def limit_buy(self, **fields):
        """Builds the body of a LIMIT buy of ten shares at 2500, intraday.

        Args:
            **fields: The fields naming the instrument, and any others to add.

        Returns:
            dict: The request body.
        """
        body = {
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': 2500,
            'quantity': 10,
        }
        body.update(fields)
        return body

    def run(self):
        """Places one order and reads it back, places a list, and runs the checks one by one.

        Returns:
            None: This method returns nothing.
        """
        with self.request('POST', 'place', body=self.limit_buy(instrument_id=RELIANCE)):
            response, status = self.blueprint.place()
        answer = response.get_json()
        print(f'place: {status} {self.shown(answer)}')
        for sent in self.network.sent_requests:
            print(f"  sent to the broker: {sent['method']} {sent['url']}")

        with self.request('GET', 'intents/' + answer['intent_id']):
            response, status = self.blueprint.intent(answer['intent_id'])
        stored = response.get_json()
        print(f"intent {answer['intent_id']}: {status} status {stored['status']}, outcome {stored['response']['outcome']}")

        dry_run = self.limit_buy(
            exchange='nse',
            segment='equities',
            symbol='RELIANCE',
            dry_run=True,
        )
        with self.request('POST', 'place', body=dry_run):
            body, status = self.blueprint.place_order(time.perf_counter())
        print(f"place_order, a dry run named by symbol: {status} broker {body['broker']}, request {self.shown(body['request'])}")

        order_list = {
            'orders': [
                self.limit_buy(instrument_id=RELIANCE),
                self.limit_buy(instrument_id=RELIANCE, dry_run=True),
                self.limit_buy(exchange='nse', segment='equities', symbol='NOSUCHSTOCK'),
                self.limit_buy(instrument_id=RELIANCE, quantity=-1),
            ],
        }
        with self.request('POST', 'place', body=order_list):
            body, status = self.blueprint.place_order_list(order_list, MAPPING_DATE, WARM_IDENTIFIER, time.perf_counter())
        print(f'place_order_list: {status}')
        for result in body['results']:
            response_body = result['response']
            if 'error' in response_body:
                print(f"  request {result['request_index']}: {result['status']} {response_body['error']}")
            else:
                print(f"  request {result['request_index']}: {result['status']} {response_body['outcome']} at {response_body['broker']}, order id {response_body['order_id']}")
        print(f'list_wait_seconds for 3 orders: {self.blueprint.list_wait_seconds(3)}')
        print(f'list_wait_seconds for 400 orders: {self.blueprint.list_wait_seconds(400)}')

        prefix = self.blueprint.catalogue_key_prefix(MAPPING_DATE)
        print(f'catalogue_key_prefix: {prefix}')
        try:
            self.blueprint.catalogue_key_prefix(None)
        except RefusedRequestError as refusal:
            print(f'catalogue_key_prefix before any mapping: {refusal.status} {refusal.body}')

        by_symbol = PlaceOrderRequest(self.limit_buy(exchange='nse', segment='equities', symbol='RELIANCE'))
        print(f'find_instrument_id RELIANCE: {self.blueprint.find_instrument_id(by_symbol, prefix)}')
        self.cache.round_trips = 0
        instrument_id = self.blueprint.resolve_instrument_id(by_symbol, MAPPING_DATE, WARM_IDENTIFIER, prefix)
        print(f'resolve_instrument_id RELIANCE: {instrument_id}, Redis round trips {self.cache.round_trips}')
        twin = PlaceOrderRequest(self.limit_buy(exchange='nse', segment='equities', symbol='TWIN'))
        try:
            self.blueprint.resolve_instrument_id(twin, MAPPING_DATE, WARM_IDENTIFIER, prefix)
        except RefusedRequestError as refusal:
            print(f'resolve_instrument_id TWIN: {refusal.status} {refusal.body}')

        token_document_text = self.cache.hashes['last_login']['unified_broker_interface']
        self.blueprint.check_access_token(API_TOKEN, token_document_text)
        print('check_access_token with the right token: accepted')
        try:
            self.blueprint.check_access_token('guessed-token', token_document_text)
        except RefusedRequestError as refusal:
            print(f'check_access_token with a guessed token: {refusal.status} {refusal.body}')
        try:
            self.blueprint.check_token('guessed-token')
        except RefusedRequestError as refusal:
            print(f'check_token with a guessed token: {refusal.status} {refusal.body}')


if __name__ == '__main__':
    PlacingOrdersExample().run()
