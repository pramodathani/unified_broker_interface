"""Offline check of changes to orders the order engine owns, against a recording of their behaviour.

Each scenario places an order through `POST /api/orders/place`, with the real engine running behind the route, and then changes it: a cancel or a modify through the ordinary routes, which hand an order the engine owns to the engine, or a cancel of the whole parent through `DELETE /api/orders/parents`. It then reads the parent back through `GET /api/orders/parents`. Every order goes to Flattrade, whose stub answers each request with its own recorded success body.

For each scenario it keeps every request's status and body, the broker requests that went out and the parent as the engine left it, and compares them with `test_runs/fixtures/order_engine_changes.jsonl`.

No Redis, database, credentials or network are used, and no request leaves the process.

Typical usage:

    python -m test_runs.order_engine_changes
    python -m test_runs.order_engine_changes --record
"""

import argparse
import copy
import datetime
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import uuid

import requests

from test_runs import engine_stand_ins
from test_runs import order_change_lists
from test_runs import order_routes
from unified_broker_interface.blueprints import base as blueprint_base
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / 'fixtures'
    / 'order_engine_changes.jsonl'
)
FLATTRADE_ORDER = order_routes.OrderRoutesState.ORDER_IDENTIFIERS['flattrade']


class OrderEngineChangesSuite(order_routes.OrderRoutesSuite):
    """Runs each change scenario as a short sequence of requests, and records or compares the results.

    Attributes:
        client (flask.testing.FlaskClient | None): The client of the scenario being run.
    """

    def __init__(self):
        """Builds the suite with the per-URL network stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.network = order_change_lists.ListBrokerNetwork()
        self.client = None

    def start_scenario(self):
        """Resets the stand-ins and builds a client whose orders all go to Flattrade.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = self.build_state()
        self.counting_uuid.reset()
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = [
            'flattrade',
        ]
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_rate_per_second'] = 0
        api_configuration['order_rate_per_broker_per_second'] = 10
        answers = order_routes.OrderRoutesAnswers()
        self.network.reset({
            'by_url': [
                [
                    'PlaceOrder',
                    answers.json_answer(200, answers.place_success('flattrade')),
                ],
            ],
        })
        self.client = self.build_client()
        self.fake_redis.inline_engine = engine_stand_ins.InlineEngine(
            self.fake_redis,
        )

    def call(self, method, path, body=None, query=None):
        """Sends one request through the client and keeps its status and body.

        Args:
            method (str): The HTTP method.
            path (str): The path under `/api/orders`.
            body (dict | None): The JSON body.
            query (dict | None): The query string.

        Returns:
            dict: `status` and `body`, with timings reduced to their names.
        """
        response = self.client.open(
            '/api/orders' + path,
            method=method,
            headers={
                'access-token': order_routes.API_TOKEN,
            },
            json=body,
            query_string=query,
        )
        answer_body = response.get_json(silent=True)
        if isinstance(answer_body, dict) and isinstance(answer_body.get('timing_ms'), dict):
            answer_body['timing_ms'] = sorted(answer_body['timing_ms'])
        return {
            'status': response.status_code,
            'body': answer_body,
        }

    def placed_limit_order(self):
        """Places a LIMIT buy of ten RELIANCE shares at 1000, which Flattrade accepts as its open order.

        Returns:
            dict: The place request's status and body.
        """
        body = order_routes.OrderRoutesScenarios().market_order(dry_run=None)
        body['order_type'] = 'LIMIT'
        body['price'] = 1000
        return self.call('POST', '/place', body)

    def parent_after(self, parent_order_id):
        """The parent as the engine left it, with each leg's broker, order id, state, quantity and prices.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict: `status`, and the parent's `state` and `legs`.
        """
        read = self.call('GET', '/parents', query={
            'parent_id': parent_order_id,
        })
        document = read['body'] or {}
        legs = []
        for leg in document.get('legs') or []:
            legs.append({
                'broker': leg.get('broker'),
                'broker_order_id': leg.get('broker_order_id'),
                'state': leg.get('state'),
                'quantity': leg.get('quantity'),
                'price': leg.get('price'),
                'trigger_price': leg.get('trigger_price'),
            })
        return {
            'status': read['status'],
            'state': document.get('state'),
            'legs': legs,
        }

    def sent(self):
        """The broker requests that went out, by method and the last part of the URL.

        Returns:
            list: One `method path` string per request, in order.
        """
        shown = []
        for request in self.network.sent_requests:
            shown.append(f"{request['method']} {request['url'].rsplit('/', 1)[-1]}")
        return shown

    def cancel_through_the_cancel_route(self):
        """Cancels an engine order through `DELETE /api/orders/cancel`.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        parent_order_id = placed['body']['parent_id']
        cancelled = self.call('DELETE', '/cancel', {
            'order_id': FLATTRADE_ORDER,
        })
        return {
            'name': 'the_cancel_route_hands_an_engine_order_to_the_engine',
            'placed': placed,
            'cancelled': cancelled,
            'sent': self.sent(),
            'parent': self.parent_after(parent_order_id),
        }

    def modify_price_through_the_modify_route(self):
        """Moves an engine order's price through `PUT /api/orders/modify`.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        parent_order_id = placed['body']['parent_id']
        modified = self.call('PUT', '/modify', {
            'order_id': FLATTRADE_ORDER,
            'price': 1001.5,
        })
        return {
            'name': 'the_modify_route_hands_a_price_change_to_the_engine',
            'placed': placed,
            'modified': modified,
            'sent': self.sent(),
            'parent': self.parent_after(parent_order_id),
        }

    def modify_order_type_is_refused(self):
        """Tries to change an engine order's validity through `PUT /api/orders/modify`, which the engine's order types cannot carry on from.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        modified = self.call('PUT', '/modify', {
            'order_id': FLATTRADE_ORDER,
            'validity': 'IOC',
        })
        return {
            'name': 'an_engine_order_cannot_have_its_validity_changed',
            'placed': placed,
            'modified': modified,
            'sent': self.sent(),
        }

    def cancel_whole_parent(self):
        """Cancels an engine parent through `DELETE /api/orders/parents`, then tries again.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        parent_order_id = placed['body']['parent_id']
        cancelled = self.call('DELETE', '/parents', {
            'parent_id': parent_order_id,
        })
        again = self.call('DELETE', '/parents', {
            'parent_id': parent_order_id,
        })
        return {
            'name': 'a_parent_is_cancelled_with_its_legs_and_only_once',
            'placed': placed,
            'cancelled': cancelled,
            'cancelled_again': again,
            'sent': self.sent(),
            'parent': self.parent_after(parent_order_id),
        }

    def list_open_parents(self):
        """Places an order and lists the engine's open parents.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        listed = self.call('GET', '/parents')
        open_parents = []
        for document in (listed['body'] or {}).get('parents') or []:
            open_parents.append({
                'is_the_placed_parent': document.get('parent_order_id') == placed['body']['parent_id'],
                'synthetic_type': document.get('synthetic_type'),
                'state': document.get('state'),
            })
        return {
            'name': 'open_parents_are_listed',
            'status': listed['status'],
            'open_parents': open_parents,
        }

    def refusals(self):
        """Parent routes asked about a parent that does not exist, or given no parent.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        return {
            'name': 'unknown_or_missing_parents_are_refused',
            'unknown_read': self.call('GET', '/parents', query={
                'parent_id': 'no-such-parent',
            }),
            'unknown_cancel': self.call('DELETE', '/parents', {
                'parent_id': 'no-such-parent',
            }),
            'missing_parent_id': self.call('DELETE', '/parents', {}),
            'empty_list': self.call('DELETE', '/parents', {
                'parents': [],
            }),
        }

    def flatten_halts_open_parents(self):
        """Places an order, then flattens, which halts the engine's open parent before cancelling anything.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        parent_order_id = placed['body']['parent_id']
        original_wait = api_configuration['order_flatten_wait_seconds']
        api_configuration['order_flatten_wait_seconds'] = 0.3
        try:
            flattened = self.call('POST', '/flatten', {
                'confirm': 'FLATTEN',
            })
        finally:
            api_configuration['order_flatten_wait_seconds'] = original_wait
        return {
            'name': 'flatten_halts_the_open_parents_before_it_cancels',
            'halted': (flattened['body'] or {}).get('halted'),
            'parent': self.parent_after(parent_order_id),
        }

    def order_book_filtered_by_parent(self):
        """Places an order, builds the day's order book with the real combiner, and reads it back by the order's parent.

        Returns:
            dict: The recorded result.
        """
        self.start_scenario()
        placed = self.placed_limit_order()
        parent_order_id = placed['body']['parent_id']
        combiner = self.orders_combiner()
        document = combiner.orders_document(
            self.fake_redis,
            combiner.Resolver(self.fake_redis),
            combiner.EngineLinks(self.fake_redis),
            datetime.datetime.now(),
        )
        self.fake_redis.strings['unified:orders:orders'] = json.dumps(document)
        by_parent = self.call('GET', '/details', query={
            'parent_id': parent_order_id,
        })
        orders = (by_parent['body'] or {}).get('orders') or []
        shown = []
        for order in orders:
            shown.append({
                'broker': order.get('broker'),
                'order_id': order.get('order_id'),
                'is_the_placed_parent': order.get('engine_parent_id') == parent_order_id,
                'leg_role': order.get('leg_role'),
                'synthetic_type': order.get('synthetic_type'),
            })
        open_page = self.call('GET', '/details', query={
            'status': 'open',
            'limit': 2,
        })
        bad_limit = self.call('GET', '/details', query={
            'limit': 0,
        })
        return {
            'name': 'the_order_book_is_filtered_by_the_engine_parent',
            'orders_in_the_day': len(document['orders']),
            'by_parent_status': by_parent['status'],
            'by_parent': shown,
            'by_parent_page': (by_parent['body'] or {}).get('page'),
            'open_page': (open_page['body'] or {}).get('page'),
            'bad_limit': bad_limit,
        }

    def orders_combiner(self):
        """The orders combiner script, loaded as a module so its document builder can run against the stand-in.

        Returns:
            module: The loaded script.
        """
        path = pathlib.Path(__file__).resolve().parents[1] / 'bin' / 'unified' / 'orders' / 'api_order_details'
        loader = importlib.machinery.SourceFileLoader('unified_api_order_details', str(path))
        specification = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(specification)
        loader.exec_module(module)
        return module

    def run_every_scenario(self):
        """Runs every scenario with Redis, MongoDB, the broker network and `uuid.uuid4` replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_get_cache = blueprint_base.get_cache
        original_get_mongo_database = blueprint_base.get_mongo_db
        original_request = requests.Session.request
        original_uuid4 = uuid.uuid4
        original_settings = copy.deepcopy(dict(api_configuration))
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_mongo_database
        requests.Session.request = self.network.request
        uuid.uuid4 = self.counting_uuid
        try:
            return [
                self.cancel_through_the_cancel_route(),
                self.modify_price_through_the_modify_route(),
                self.modify_order_type_is_refused(),
                self.cancel_whole_parent(),
                self.list_open_parents(),
                self.refusals(),
                self.flatten_halts_open_parents(),
                self.order_book_filtered_by_parent(),
            ]
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            api_configuration.update(original_settings)

    def record(self, results):
        """Writes the results to this suite's fixture file, one scenario per line.

        Args:
            results (list): The results.

        Returns:
            int: The exit code, always 0.
        """
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for result in results:
            lines.append(self.encode(result))
        FIXTURE_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'recorded {len(results)} scenarios to {FIXTURE_PATH}')
        return 0

    def read_recording(self):
        """Reads this suite's fixture file.

        Returns:
            dict: Scenario names to recorded results, in file order.
        """
        recorded = {}
        for line in FIXTURE_PATH.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            recorded_result = json.loads(line)
            recorded[recorded_result['name']] = recorded_result
        return recorded

    def run(self):
        """Runs the suite from the command line.

        Returns:
            int: The exit code.
        """
        parser = argparse.ArgumentParser(
            description='Check changes to orders the engine owns against their recorded behaviour.',
        )
        parser.add_argument(
            '--record',
            action='store_true',
            help='rewrite the recording from the current code',
        )
        arguments = parser.parse_args()
        results = self.run_every_scenario()
        if arguments.record:
            return self.record(results)
        return self.compare(results)


if __name__ == '__main__':
    sys.exit(OrderEngineChangesSuite().run())
