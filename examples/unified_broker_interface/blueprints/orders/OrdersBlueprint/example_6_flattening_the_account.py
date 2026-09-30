"""Flattens the account through `POST /api/orders/flatten`, the panic button, and runs each of its steps on its own.

Flatten cancels every open order at every broker, waits until the brokers' own order books agree the orders are gone, and only then closes every position, at the broker holding it, through the order engine; it then waits until the positions show zero. The order matters: a stop or target still live when its position closes would fill afterwards and open a new position the other way. Before any of that it asks the engine to halt every parent, so nothing the engine manages places a new order. The body must carry `confirm` set to `FLATTEN`, and `dry_run` reports what would happen without sending anything.

This program uses the in-memory Redis stand-in of the offline flatten suite, `test_runs/order_flatten.py`, in which Flattrade holds one open order and a long intraday position of ten RELIANCE shares, and whose books show the order cancelled and the position closed from their second read onward, as a broker's poller would a moment after the cancel and the close. The real order engine runs on the same thread, the broker network is a stub that accepts everything, and flatten waits at most 0.6 seconds for the books, so the program finishes in about two seconds.

Notice that the broker requests of the real flatten show the cancel going out before the closing order, and that `halt_every_parent` in the second half finds one open parent: the simple order the engine placed to close the position in the first half, which the engine still holds until it sees the fill.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/orders/OrdersBlueprint/example_6_flattening_the_account.py
"""

import json
import time
import uuid

import flask
import requests

from test_runs import engine_stand_ins
from test_runs.order_flatten import (
    FakeFlattenRedis,
    OrderFlattenScenarios,
)
from test_runs.order_routes import (
    API_TOKEN,
    BROKER_NAMES,
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
from utilities.configurations import api_configuration

ORDER_ID = '26091500000021'


class FlatteningTheAccountExample:
    """Flattens the account through the route and step by step, and prints what each step does.

    Attributes:
        cache (FakeFlattenRedis): The stand-in Redis client the blueprint and the order engine share.
        network (FakeBrokerNetwork): The stub every broker request goes to.
        blueprint (OrdersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
        scenarios (OrderFlattenScenarios): The flatten suite's builders of order book and position entries.
    """

    def __init__(self):
        """Builds the blueprint and has the stub network accept every cancel and every order.

        Returns:
            None: This method returns nothing.
        """
        self.cache = None
        self.network = None
        self.blueprint = None
        self.application = None
        self.scenarios = OrderFlattenScenarios()
        self.build_blueprint()
        self.network.reset(self.scenarios.accepted())

    def stand_in_cache(self):
        """Hands a newly built blueprint the stand-in instead of a Redis client.

        Returns:
            FakeFlattenRedis: The stand-in.
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

        The blueprint opens its stores through `get_cache` and `get_mongo_db` while it is built, and hands the Redis client on to the objects it builds, so those two functions are pointed at the stand-ins first. Configuration is set so that no broker is excluded, no connection is warmed, at most ten orders a second go to each broker, and flatten waits at most 0.6 seconds for the brokers' books to change.

        Returns:
            None: This method returns nothing.
        """
        starting_state = OrderRoutesState().build()
        self.cache = FakeFlattenRedis()
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
        api_configuration['order_flatten_wait_seconds'] = 0.6
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

    def fill_books(self):
        """Puts Flattrade's open order and long position back in the books, with the cancelled order and flat position served from the second read onward.

        Returns:
            None: This method returns nothing.
        """
        for broker_name in BROKER_NAMES:
            self.cache.hashes[f'{broker_name}:orders:orders'] = {}
            self.cache.hashes[f'{broker_name}:portfolio:positions'] = {}
        self.cache.hashes['flattrade:orders:orders'] = {
            ORDER_ID: self.scenarios.order_entry(ORDER_ID, 'OPEN'),
        }
        self.cache.hashes['flattrade:portfolio:positions'] = {
            'RELIANCE-MIS': self.scenarios.position_entry(10),
        }
        self.cache.later_hashes['flattrade:orders:orders'] = {
            ORDER_ID: self.scenarios.order_entry(ORDER_ID, 'CANCELLED'),
        }
        self.cache.later_hashes['flattrade:portfolio:positions'] = {
            'RELIANCE-MIS': self.scenarios.position_entry(0),
        }
        self.cache.reads = {}
        self.cache.hashes['unified:broker_tokens'] = {
            'flattrade:1': json.dumps([
                OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
            ]),
        }
        self.network.sent_requests = []

    def through_the_route(self):
        """Sends flatten without the confirmation, as a dry run, and for real.

        Returns:
            None: This method returns nothing.
        """
        self.fill_books()
        with self.request('POST', 'flatten', body={}):
            self.show('flatten without confirm', self.blueprint.flatten())
        dry_run = {
            'confirm': 'FLATTEN',
            'dry_run': True,
        }
        with self.request('POST', 'flatten', body=dry_run):
            body, status = self.blueprint.flatten_everything(time.perf_counter())
        print(f'flatten_everything, a dry run: {status} {self.shown(body)}')
        self.fill_books()
        with self.request(
            'POST',
            'flatten',
            body={
                'confirm': 'FLATTEN',
            },
        ):
            response, status = self.blueprint.flatten()
        answer = response.get_json()
        print(f"flatten: {status} flat {answer['flat']}, halted {answer['halted']}")
        for cancelled in answer['cancelled']:
            print(f"  cancelled {cancelled['broker']} {cancelled['order_id']}: {cancelled['outcome']}")
        for closed in answer['closed']:
            print(f"  closed {closed['broker']} {closed['close_quantity']} by {closed['transaction_type']}: {closed['outcome']}")
        for sent in self.network.sent_requests:
            print(f"  sent to the broker, in this order: {sent['method']} {sent['url']}")

    def step_by_step(self):
        """Runs flatten's steps one at a time over fresh books.

        Returns:
            None: This method returns nothing.
        """
        self.fill_books()
        with self.request('POST', 'flatten'):
            print(f'halt_every_parent: {self.blueprint.halt_every_parent(time.perf_counter())}')
        replies = []
        for broker_name in self.blueprint.broker_names:
            replies.append(self.cache.hashes[f'{broker_name}:orders:orders'])
        order_books = self.blueprint.decode_books(replies)
        print(f"decode_books: flattrade holds {list(order_books['flattrade'])}")
        cancelling = self.blueprint.kill_switch.orders_to_cancel(order_books)
        print(f'shown_cancels: {self.blueprint.shown_cancels(cancelling)}')
        login_texts = []
        settings_texts = []
        for broker_name in self.blueprint.broker_names:
            login_texts.append(self.cache.hashes['last_login'].get(broker_name))
            settings_texts.append(self.cache.hashes['settings'].get(broker_name))
        print(f'cancel_every_order: {self.blueprint.cancel_every_order(cancelling, login_texts, settings_texts)}')
        broker_orders = self.blueprint.broker_orders['flattrade']
        login = broker_orders.decode_login(None)
        settings = broker_orders.decode_settings(None)
        print(f'cancel_one_order without a login: {self.blueprint.cancel_one_order(broker_orders, cancelling[0], login, settings)}')
        print(f'wait_for_cancels: still open {self.blueprint.wait_for_cancels(cancelling)}')

        position_replies = []
        for broker_name in self.blueprint.broker_names:
            position_replies.append(self.cache.hashes[f'{broker_name}:portfolio:positions'])
        position_books = self.blueprint.decode_books(position_replies)
        closing = self.blueprint.kill_switch.positions_to_close(position_books)
        instrument_id = self.blueprint.instrument_for_broker_token('flattrade', '1')
        print(f'instrument_for_broker_token flattrade 1: {instrument_id}')
        print(f"instrument_for_broker_token flattrade 999999: {self.blueprint.instrument_for_broker_token('flattrade', '999999')}")
        print(f'closing_body: {self.shown(self.blueprint.closing_body(closing[0], instrument_id))}')
        for product in [
            'delivery',
            'intraday',
            'margin',
        ]:
            print(f'closing_product {product}: {self.blueprint.closing_product(product)}')
        with self.request('POST', 'flatten'):
            closed = self.blueprint.close_every_position(closing, time.perf_counter())
        print(f"close_every_position: sent {closed[0]['sent']}, outcome {closed[0]['outcome']}, order id {closed[0]['order_id']}")
        print(f'wait_for_positions: still held {self.blueprint.wait_for_positions(closed)}')

    def run(self):
        """Flattens through the route, then step by step.

        Returns:
            None: This method returns nothing.
        """
        self.through_the_route()
        self.step_by_step()


if __name__ == '__main__':
    FlatteningTheAccountExample().run()
