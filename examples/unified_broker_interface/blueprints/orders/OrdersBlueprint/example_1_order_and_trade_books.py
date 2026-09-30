"""Reads the day's order and trade books, and the order engine's parents, through `/api/orders`.

`GET /api/orders/details` and `GET /api/orders/trades` answer with the documents `bin/unified/orders/api_order_details` and `api_trade_details` keep in Redis, `unified:orders:orders` and `unified:orders:trades`, narrowed by any filters in the query string such as `broker` or `status`. `GET /api/orders/parents` answers with the order engine's parents, the orders it was asked for, such as a bracket, whose legs are the broker orders it placed. `GET /api/orders/intents/<intent_id>` answers what the engine did with one order, once it has answered. None of these asks a broker.

This program builds the blueprint over the in-memory Redis stand-in of the offline order route suite, `test_runs/order_routes.py`, with the broker network replaced by a stub that records every request, and calls each handler inside a Flask request context. It writes the order and trade documents with `as_of` set to the moment it runs, as a running script would, and never prints `as_of` or `timing_ms`, so the output is the same on every run. It also shows the two refusals every order route builds, `refuse` and `redis_unreadable`, which are raised as `RefusedRequestError` and answered as JSON.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_1_order_and_trade_books.py
"""

import datetime
import json
import uuid

import flask
import redis
import requests

from test_runs import engine_stand_ins
from test_runs import redis_stand_ins
from test_runs.order_routes import (
    API_TOKEN,
    FakeBrokerNetwork,
    OrderRoutesState,
)
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints.orders import (
    OrdersBlueprint,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    OPEN_KEY,
    PARENTS_KEY,
)
from utilities.configurations import api_configuration


class OrderAndTradeBooksExample:
    """Writes the day's books and two parents into the stand-in, and prints what the reading routes answer.

    Attributes:
        cache (redis_stand_ins.InlineEngineRedis): The stand-in Redis client the blueprint and the order engine share.
        network (FakeBrokerNetwork): The stub every broker request goes to.
        blueprint (OrdersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint and writes the books and parents.

        Returns:
            None: This method returns nothing.
        """
        self.cache = None
        self.network = None
        self.blueprint = None
        self.application = None
        self.build_blueprint()
        written_now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        brokers = [
            {
                'broker': 'zerodha',
                'status': 'ok',
            },
            {
                'broker': 'dhan',
                'status': 'ok',
            },
        ]
        self.cache.strings['unified:orders:orders'] = json.dumps({
            'orders': [
                {
                    'broker': 'zerodha',
                    'order_id': '250915000000011',
                    'status': 'OPEN',
                    'tradingsymbol': 'RELIANCE',
                },
                {
                    'broker': 'zerodha',
                    'order_id': '250915000000012',
                    'status': 'COMPLETE',
                    'tradingsymbol': 'INFY',
                },
                {
                    'broker': 'dhan',
                    'order_id': '112509150000012',
                    'status': 'OPEN',
                    'tradingsymbol': 'RELIANCE',
                },
            ],
            'brokers': brokers,
            'as_of': written_now,
        })
        self.cache.strings['unified:orders:trades'] = json.dumps({
            'trades': [
                {
                    'broker': 'zerodha',
                    'order_id': '250915000000012',
                    'trade_id': 'T-1',
                    'quantity': 5,
                    'price': 1521.4,
                },
            ],
            'brokers': brokers,
            'as_of': written_now,
        })
        self.cache.hashes[PARENTS_KEY] = {
            'P-1': json.dumps({
                'parent_id': 'P-1',
                'type': 'bracket',
                'state': 'working',
            }),
            'P-2': json.dumps({
                'parent_id': 'P-2',
                'type': 'trigger',
                'state': 'armed',
            }),
        }
        self.cache.sets[OPEN_KEY] = {
            'P-1',
            'P-2',
        }

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

    def run(self):
        """Reads the books with and without filters, the parents, an unknown intent, and builds the two refusals.

        Returns:
            None: This method returns nothing.
        """
        with self.request('GET', 'details'):
            response, status = self.blueprint.details()
        order_ids = []
        for order in response.get_json()['orders']:
            order_ids.append(order['order_id'])
        print(f'details: {status} {order_ids}')

        with self.request(
            'GET',
            'details',
            query={
                'broker': 'zerodha',
                'status': 'open',
            },
        ):
            response, status = self.blueprint.details()
        print(f"details of zerodha's open orders: {status} {self.shown(response.get_json()['orders'])}")

        with self.request('GET', 'trades'):
            response, status = self.blueprint.trades()
        print(f"trades: {status} {self.shown(response.get_json()['trades'])}")

        stored_book = {
            'orders': [
                {
                    'broker': 'dhan',
                    'order_id': '1',
                    'status': 'OPEN',
                },
                {
                    'broker': 'dhan',
                    'order_id': '2',
                    'status': 'REJECTED',
                },
            ],
        }
        with self.request(
            'GET',
            'details',
            query={
                'status': 'REJECTED',
            },
        ):
            self.show('filtered to REJECTED', self.blueprint.filtered(stored_book, 200, 'orders'))
        with self.request(
            'GET',
            'details',
            query={
                'limit': 'lots',
            },
        ):
            self.show('filtered with an unreadable limit', self.blueprint.filtered(stored_book, 200, 'orders'))

        with self.request('GET', 'parents'):
            self.show('parents', self.blueprint.parents())
        with self.request(
            'GET',
            'parents',
            query={
                'parent_id': 'P-2',
            },
        ):
            self.show('parent P-2', self.blueprint.parents())
        with self.request(
            'GET',
            'parents',
            query={
                'parent_id': 'P-9',
            },
        ):
            self.show('parent P-9', self.blueprint.parents())

        with self.request('GET', 'intents/not-an-intent'):
            self.show('intent not-an-intent', self.blueprint.intent('not-an-intent'))

        refusal = self.blueprint.refuse('the order is already COMPLETE', 409, broker='zerodha', order_id='250915000000012')
        print(f'refuse: {refusal.status} {self.shown(refusal.body)}')
        refusal = self.blueprint.redis_unreadable(redis.RedisError('Connection refused'))
        print(f'redis_unreadable: {refusal.status} {self.shown(refusal.body)}')


if __name__ == '__main__':
    OrderAndTradeBooksExample().run()
