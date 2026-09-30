"""Changes one open order through `PUT /api/orders/modify`, and walks through each step the route takes before it calls the broker.

The route finds the broker whose order book in Redis holds the order id, reads the stored order, lays the change over it, finds the order's instrument in the day's catalogue from the broker's token so a changed quantity can be checked against the lot size and turned into the broker's terms, builds the broker's request, takes room in the per-broker rate budget, and sends it. An order the order engine placed is instead handed to the engine, so the order type that owns it carries on from the change, and only its price, trigger price and quantity may be changed.

This program uses the in-memory Redis stand-in and the recorded order books and catalogue of the offline order route suite, `test_runs/order_routes.py`, in which Zerodha holds an open LIMIT buy of ten RELIANCE shares at 2500, order `250915000000011`. The broker network is a stub that accepts every change and records it, so nothing leaves the process. The program first sends a dry run and a real change through the route, then calls each step's method on its own.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_3_modifying_one_order.py
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
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    CHILDREN_KEY,
)
from utilities.configurations import api_configuration

ORDER_ID = OrderRoutesState.ORDER_IDENTIFIERS['zerodha']


class ModifyingOneOrderExample:
    """Modifies Zerodha's open order through the route and step by step, and prints what each step answers.

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
                'data': {
                    'order_id': ORDER_ID,
                },
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
        """Modifies the order through the route, then runs each step on its own.

        Returns:
            None: This method returns nothing.
        """
        dry_run = {
            'order_id': ORDER_ID,
            'price': 2501,
            'quantity': 20,
            'dry_run': True,
        }
        with self.request('PUT', 'modify', body=dry_run):
            self.show('modify, a dry run', self.blueprint.modify())
        change = {
            'order_id': ORDER_ID,
            'price': 2502.5,
        }
        with self.request('PUT', 'modify', body=change):
            response, status = self.blueprint.modify_order(time.perf_counter())
        print(f'modify_order: {status} {self.shown(response.get_json())}')
        for sent in self.network.sent_requests:
            print(f"  sent to the broker: {sent['method']} {sent['url']} {sent['data']}")

        state = self.blueprint.read_order_state(
            [
                ORDER_ID,
            ],
            True,
        )
        print(f"read_order_state: mapping date {state['mapping_date_text']}, warm {state['warm_identifier']}, {len(state['order_texts'][ORDER_ID])} order book entries read")
        with self.request('PUT', 'modify'):
            modify_request = ModifyOrderRequest(
                {
                    'order_id': ORDER_ID,
                    'quantity': 20,
                },
                flask.request.args,
                self.blueprint.broker_names,
            )
        broker_name, stored_order = self.blueprint.find_stored_order(modify_request, state['order_texts'][ORDER_ID])
        print(f'find_stored_order: {broker_name} holds it, status {stored_order.status}')
        broker_orders = self.blueprint.broker_orders[broker_name]
        modification = OrderModification(modify_request, stored_order)
        instrument = self.blueprint.resolve_order_instrument(
            broker_orders,
            modification,
            state['mapping_date_text'],
            state['warm_identifier'],
        )
        print(f'resolve_order_instrument: {instrument.instrument_id}')
        converted = self.blueprint.convert_modified_quantities(
            broker_orders,
            modify_request,
            modification,
            instrument,
        )
        print(f'convert_modified_quantities: quantity {converted.quantity}, disclosed {converted.disclosed_quantity}')
        prepared = self.blueprint.prepare_modification(modify_request, state)
        print(f'prepare_modification: {type(prepared).__name__} for {prepared.broker_name}, engine command {prepared.engine_command}')
        self.blueprint.take_rate_room('zerodha')
        print('take_rate_room: room taken for zerodha')
        body, status = self.blueprint.send_change(prepared, time.perf_counter())
        print(f"send_change: {status} outcome {body['outcome']}")

        print(f'owning_parent before the engine owns it: {self.blueprint.owning_parent(state, ORDER_ID, broker_name)}')
        self.cache.hashes[CHILDREN_KEY] = {
            f'zerodha:{ORDER_ID}': 'P-7',
        }
        state = self.blueprint.read_order_state(
            [
                ORDER_ID,
            ],
            True,
        )
        owner = self.blueprint.owning_parent(state, ORDER_ID, broker_name)
        print(f'owning_parent once the engine owns it: {owner}')
        arguments = self.blueprint.engine_modification(owner, broker_name, ORDER_ID, modify_request, converted)
        print(f'engine_modification: {self.shown(arguments)}')
        with self.request('PUT', 'modify'):
            type_change = ModifyOrderRequest(
                {
                    'order_id': ORDER_ID,
                    'order_type': 'MARKET',
                },
                flask.request.args,
                self.blueprint.broker_names,
            )
        try:
            self.blueprint.refuse_engine_unsupported_change(
                OrderModification(type_change, stored_order),
                broker_name,
                ORDER_ID,
            )
        except RefusedRequestError as refusal:
            print(f"refuse_engine_unsupported_change: {refusal.status} {refusal.body['error']}")


if __name__ == '__main__':
    ModifyingOneOrderExample().run()
