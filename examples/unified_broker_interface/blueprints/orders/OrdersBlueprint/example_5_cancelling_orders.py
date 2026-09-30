"""Cancels orders through `DELETE /api/orders/cancel`, one at a time and as a list, and cancels the order engine's parents through `DELETE /api/orders/parents`.

The cancel route finds the broker whose order book in Redis holds the order id, refuses an order that has already finished, builds the broker's cancel request and sends it, or with `dry_run` shows the request instead. A list is read from Redis in one round trip and answered entry by entry. An order the engine placed is cancelled by the engine instead, on the worker that owns its parent. Cancelling a parent itself, such as a bracket or an armed trigger, cancels every leg still resting at a broker as well as the parent.

This program uses the in-memory Redis stand-in and the recorded order books of the offline order route suite, `test_runs/order_routes.py`, in which Zerodha and Flattrade each hold an open order and Zerodha also holds a completed one. It runs the real order engine on the same thread whenever the route waits for it, and answers every broker request with a stub that accepts it, so nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_5_cancelling_orders.py
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
    OrderRoutesState,
)
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints.orders import (
    OrdersBlueprint,
)
from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    CHILDREN_KEY,
)
from utilities.configurations import api_configuration

ZERODHA_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['zerodha']
FLATTRADE_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['flattrade']
FINISHED_ORDER = '250915000000099'


class CancellingOrdersExample:
    """Cancels single orders, a list and parents, and prints each answer.

    Attributes:
        cache (redis_stand_ins.InlineEngineRedis): The stand-in Redis client the blueprint and the order engine share.
        network (FakeBrokerNetwork): The stub every broker request goes to.
        blueprint (OrdersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint and has the stub network accept every cancel.

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
            'json': {
                'status': 'success',
                'stat': 'Ok',
                's': 'ok',
                'type': 'success',
            },
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

    def run(self):
        """Cancels one order, shows a dry run, cancels a list, prepares one cancel by hand, and cancels parents.

        Returns:
            None: This method returns nothing.
        """
        with self.request(
            'DELETE',
            'cancel',
            body={
                'order_id': ZERODHA_ORDER,
            },
        ):
            self.show('cancel', self.blueprint.cancel())
        for sent in self.network.sent_requests:
            print(f"  sent to the broker: {sent['method']} {sent['url']}")

        with self.request(
            'DELETE',
            'cancel',
            query={
                'order_id': FLATTRADE_ORDER,
                'dry_run': 'true',
            },
        ):
            response, status = self.blueprint.cancel_order(time.perf_counter())
        print(f'cancel_order, a dry run named in the query string: {status} {self.shown(response.get_json())}')

        cancel_list = {
            'orders': [
                {
                    'order_id': FLATTRADE_ORDER,
                },
                {
                    'order_id': FINISHED_ORDER,
                },
                {
                    'order_id': 'NOSUCHORDER',
                },
            ],
        }
        with self.request('DELETE', 'cancel', body=cancel_list):
            response, status = self.blueprint.cancel_order_list(API_TOKEN, cancel_list, time.perf_counter())
        print(f'cancel_order_list: {status}')
        for result in response.get_json()['results']:
            response_body = result['response']
            if 'error' in response_body:
                print(f"  request {result['request_index']}: {result['status']} {response_body['error']}")
            else:
                print(f"  request {result['request_index']}: {result['status']} {response_body['broker']} {response_body['outcome']}")

        self.cache.hashes[CHILDREN_KEY] = {
            f'zerodha:{ZERODHA_ORDER}': 'P-7',
        }
        state = self.blueprint.read_order_state(
            [
                ZERODHA_ORDER,
            ],
            False,
        )
        with self.request('DELETE', 'cancel'):
            cancel_request = CancelOrderRequest(
                {
                    'order_id': ZERODHA_ORDER,
                },
                flask.request.args,
                self.blueprint.broker_names,
            )
        prepared = self.blueprint.prepare_cancel(cancel_request, state)
        print(f'prepare_cancel of an order the engine placed: {prepared.broker_name}, engine command {prepared.engine_command} {self.shown(prepared.engine_arguments)}')

        with self.request(
            'DELETE',
            'parents',
            body={
                'parent_id': 'P-9',
            },
        ):
            self.show('cancel_parents, one the engine does not hold', self.blueprint.cancel_parents())
        with self.request('DELETE', 'parents', body={}):
            self.show('cancel_parents without a parent_id', self.blueprint.cancel_parents())
        parent_list = {
            'parents': [
                {
                    'parent_id': 'P-9',
                },
                {
                    'parent': 'misspelt',
                },
            ],
        }
        with self.request('DELETE', 'parents', body=parent_list):
            body, status = self.blueprint.cancel_parent_list(parent_list, time.perf_counter())
        print(f'cancel_parent_list: {status} {self.shown(body)}')


if __name__ == '__main__':
    CancellingOrdersExample().run()
