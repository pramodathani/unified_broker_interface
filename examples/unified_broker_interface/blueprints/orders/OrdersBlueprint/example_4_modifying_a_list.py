"""Changes several orders in one `PUT /api/orders/modify` request, with a body holding an `orders` list, and changes an order the engine is still holding.

A list is read from Redis in one round trip however many orders it names, every order is checked as a single modification is, and the changes that pass are sent to their brokers up to four at a time; each entry is answered on its own, so one refusal never hides the others. An entry that names `parent_id` rather than `order_id` is an order the order engine is still holding, such as a virtual limit order, and is changed by the engine without any broker being asked.

This program uses the in-memory Redis stand-in and the recorded order books and catalogue of the offline order route suite, `test_runs/order_routes.py`, runs the real order engine on the same thread when the route waits for it, and answers every broker request with a stub that accepts it. It first calls the methods the list form is built from one at a time, on a worker that has read nothing yet, and then sends lists through the route. Two changes sent together go out on two threads, so the program prints the broker requests sorted rather than in the order they happened to be sent.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_4_modifying_a_list.py
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
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_change_list import (
    OrderChangeList,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from utilities.configurations import api_configuration

ZERODHA_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['zerodha']
DHAN_ORDER = OrderRoutesState.ORDER_IDENTIFIERS['dhan']


class ModifyingAListExample:
    """Modifies a list of orders through the route and step by step, and prints each entry's answer.

    Attributes:
        cache (redis_stand_ins.InlineEngineRedis): The stand-in Redis client the blueprint and the order engine share.
        network (FakeBrokerNetwork): The stub every broker request goes to.
        blueprint (OrdersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint and has the stub network accept every change.

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

    def show_results(self, title, results):
        """Prints one line per entry of a list's answer.

        Args:
            title (str): What the list was.
            results (list): The answer's entries, each with `request_index`, `status` and `response`.

        Returns:
            None: This method returns nothing.
        """
        print(title)
        for result in results:
            response_body = result['response']
            if 'error' in response_body:
                print(f"  request {result['request_index']}: {result['status']} {response_body['error']}")
            else:
                print(f"  request {result['request_index']}: {result['status']} {response_body.get('broker')} {response_body.get('order_id')} {response_body.get('outcome')}")

    def step_by_step(self):
        """Builds a list, reads its state, warms its instruments, prepares each change, answers them as a dry run and sends one.

        Returns:
            None: This method returns nothing.
        """
        broker_list = {
            'orders': [
                {
                    'order_id': ZERODHA_ORDER,
                    'quantity': 30,
                },
                {
                    'order_id': DHAN_ORDER,
                    'price': 2499,
                },
            ],
        }
        with self.request('PUT', 'modify', body=broker_list):
            order_list = OrderChangeList(
                broker_list,
                flask.request.args,
                ModifyOrderRequest,
                self.blueprint.broker_names,
            )
        state = self.blueprint.read_order_state(order_list.order_ids(), True)
        self.cache.round_trips = 0
        self.blueprint.warm_order_instruments(order_list, state)
        print(f'warm_order_instruments: {self.cache.round_trips} Redis round trips to read the instruments of both orders')
        prepared_entries = []
        for entry in order_list.entries:
            prepared_entries.append(self.blueprint.prepare_modification(entry, state))
        answers = self.blueprint.answer_prepared_list(prepared_entries, True, time.perf_counter())
        print('answer_prepared_list as a dry run:')
        for answer_body, status in answers:
            print(f"  {status} {answer_body['broker']} {self.shown(answer_body['request'])}")
        answer_body, status = self.blueprint.send_prepared(prepared_entries[0], time.perf_counter())
        print(f"send_prepared: {status} {answer_body['broker']} {answer_body['outcome']}")


    def through_the_route(self):
        """Sends a list through the route and through `modify_order_list`, a repeated order through `broker_order_results`, and a held order's change.

        Returns:
            None: This method returns nothing.
        """
        self.network.sent_requests = []
        body = {
            'orders': [
                {
                    'order_id': ZERODHA_ORDER,
                    'price': 2505,
                },
                {
                    'order_id': DHAN_ORDER,
                    'quantity': 15,
                },
                {
                    'order_id': 'NOSUCHORDER',
                    'price': 10,
                },
                {
                    'parent_id': 'P-9',
                    'price': 101,
                },
            ],
        }
        with self.request('PUT', 'modify', body=body):
            response, status = self.blueprint.modify()
        self.show_results(f'modify of a list: {status}', response.get_json()['results'])
        sent_lines = []
        for sent in self.network.sent_requests:
            sent_lines.append(f"{sent['method']} {sent['url']}")
        for line in sorted(sent_lines):
            print(f'  sent to the broker: {line}')

        with self.request('PUT', 'modify', body=body):
            response, status = self.blueprint.modify_order_list(API_TOKEN, body, time.perf_counter())
        self.show_results(f'modify_order_list, the same list again: {status}', response.get_json()['results'])

        repeated_list = {
            'orders': [
                {
                    'order_id': ZERODHA_ORDER,
                    'price': 2506,
                },
                {
                    'order_id': ZERODHA_ORDER,
                    'price': 2507,
                },
            ],
            'dry_run': True,
        }
        with self.request('PUT', 'modify', body=repeated_list):
            results = self.blueprint.broker_order_results(API_TOKEN, repeated_list, time.perf_counter())
        self.show_results('broker_order_results, one order named twice, as a dry run:', results)

        held_change = {
            'parent_id': 'P-9',
            'price': 101,
        }
        with self.request('PUT', 'modify', body=held_change):
            self.show('modify_held_order, a parent the engine does not hold', self.blueprint.modify_held_order(API_TOKEN, held_change, time.perf_counter()))

    def run(self):
        """Runs the steps of a list one at a time, then sends lists through the route.

        Returns:
            None: This method returns nothing.
        """
        self.step_by_step()
        self.through_the_route()


if __name__ == '__main__':
    ModifyingAListExample().run()
