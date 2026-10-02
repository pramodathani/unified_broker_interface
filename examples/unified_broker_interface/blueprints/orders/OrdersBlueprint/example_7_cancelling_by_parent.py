"""Cancels orders the engine manages through `DELETE /api/orders/cancel` by naming their `parent_id`, alone and inside a list beside broker orders.

An order the order engine manages, such as an armed trigger or the exits of a bracket plan that have not been sent, has no broker order id yet, so the cancel route also takes its `parent_id`, and optionally the `part` of a plan, as `GET /api/orders/parents` shows it. The route hands such a cancel to the engine as a `cancel_parent` command, on the worker that owns the parent, without reading any broker's order book. A body that also names `order_id` or `broker` is refused with HTTP 400 before the engine is asked.

A list may mix both kinds of item. The broker orders are read from Redis in one round trip and answered as single cancels are, the parents are handed to the engine, and the answers come back in the caller's order. The list's `dry_run` covers every item, so the dry run below sends nothing to any broker.

This program uses the in-memory Redis stand-in and the recorded order books of the offline order route suite, `test_runs/order_routes.py`, in which Zerodha and Flattrade each hold an open order. It runs the real order engine on the same thread whenever the route waits for it, and answers every broker request with a stub that accepts it, so nothing leaves the process. The engine holds no parent here, so it answers each cancel by `parent_id` with 404.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_7_cancelling_by_parent.py
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
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from utilities.configurations import api_configuration

ZERODHA_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['zerodha']
FLATTRADE_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['flattrade']


class CancellingByParentExample:
    """Cancels parents by `parent_id`, singly and in a mixed list, and prints each answer.

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

    def cancel_one_parent(self):
        """Cancels a parent through the route and through `cancel_named_parent`, and has a body naming both kinds refused.

        Returns:
            None: This method returns nothing.
        """
        whole_parent = {
            'parent_id': 'P-9',
        }
        with self.request('DELETE', 'cancel', body=whole_parent):
            self.show('cancel of a parent the engine does not hold', self.blueprint.cancel())

        plan_part = {
            'parent_id': 'P-9',
            'part': 'root.each_fill.children.0',
            'dry_run': True,
        }
        with self.request('DELETE', 'cancel', body=plan_part):
            self.show('cancel_named_parent, one part as a dry run', self.blueprint.cancel_named_parent(API_TOKEN, plan_part, time.perf_counter()))

        both_kinds = {
            'parent_id': 'P-9',
            'order_id': ZERODHA_ORDER,
        }
        with self.request('DELETE', 'cancel', body=both_kinds):
            try:
                self.blueprint.cancel_named_parent(API_TOKEN, both_kinds, time.perf_counter())
            except RefusedRequestError as refusal:
                print(f'cancel_named_parent with order_id beside parent_id: {refusal.status} {self.shown(refusal.body)}')

    def cancel_a_mixed_list(self):
        """Sends a dry run of a list mixing broker orders and parents through the route, and prints each entry's answer.

        Returns:
            None: This method returns nothing.
        """
        self.network.sent_requests = []
        mixed_list = {
            'orders': [
                {
                    'order_id': ZERODHA_ORDER,
                },
                {
                    'parent_id': 'P-9',
                },
                {
                    'order_id': FLATTRADE_ORDER,
                },
                {
                    'parent_id': 'P-9',
                    'part': 'root.each_fill.children.1',
                },
                {
                    'parent_id': 'P-9',
                    'broker': 'zerodha',
                },
            ],
            'dry_run': True,
        }
        with self.request('DELETE', 'cancel', body=mixed_list):
            response, status = self.blueprint.cancel()
        print(f'cancel of a mixed list, as a dry run: {status}')
        for result in response.get_json()['results']:
            response_body = result['response']
            if 'error' in response_body:
                print(f"  request {result['request_index']}: {result['status']} {response_body['error']}")
            else:
                print(f"  request {result['request_index']}: {result['status']} {response_body['broker']} {response_body['order_id']} dry_run {response_body.get('dry_run')}")
        print(f'Requests sent to a broker: {len(self.network.sent_requests)}')

    def run(self):
        """Cancels single parents, then a mixed list.

        Returns:
            None: This method returns nothing.
        """
        self.cancel_one_parent()
        self.cancel_a_mixed_list()


if __name__ == '__main__':
    CancellingByParentExample().run()
