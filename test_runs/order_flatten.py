"""Offline check of `POST /api/orders/flatten` against a recording of its behaviour.

Runs the panic button in-process through Flask's test client, with Redis replaced by an in-memory stand-in and every broker call answered by a stub. For each scenario it keeps the HTTP status, the response body, every request that would have reached a broker and the number of Redis round trips, and compares them with `test_runs/fixtures/order_flatten.jsonl`.

The one thing this route must get right is the order of its two halves: every open order is cancelled and confirmed gone before any position is closed, because a protective order still live when its position closes will fill afterwards and open a new position the other way. The recording pins that by keeping every broker request in the order it was sent, so a cancel appearing after a close would change the recording.

The brokers' order books are made to report the cancelled orders as `CANCELLED` from the second read onward, which is what the pollers do a moment after a cancel reaches a broker. A scenario can leave them open instead, to check what the route says when a cancel is not confirmed.

No Redis, database, credentials or network are used, and no request leaves the process. The project's `.env` still has to exist, because importing the blueprint imports `utilities.configurations`.

Typical usage:

    python -m test_runs.order_flatten
    python -m test_runs.order_flatten --record
"""

import argparse
import copy
import json
import pathlib
import sys
import uuid

import flask
import requests

from test_runs import order_engine
from test_runs import order_routes
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints import orders as orders_blueprint
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent / 'fixtures' / 'order_flatten.jsonl'
)


class FakeFlattenRedis(order_engine.FakeEngineStoreRedis):
    """The engine suite's stand-in, with order books that change after they are first read.

    A real cancel is not reflected in `<broker>:orders:orders` instantly; the broker's poller or its order websocket writes the new status a moment later, and the route re-reads until it sees it. Serving one set of entries on the first read and another afterwards is how that is modelled without any waiting.

    Attributes:
        later_hashes (dict): Hash keys to what they hold from the second read onward.
        reads (dict): How many times each hash has been read.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.later_hashes = {}
        self.reads = {}

    def run_hgetall(self, key):
        """Every field in a hash, serving the later contents once it has been read before.

        Args:
            key (str): The hash key.

        Returns:
            dict: The fields and values.
        """
        seen = self.reads.get(key, 0)
        self.reads[key] = seen + 1
        if seen >= 1 and key in self.later_hashes:
            return dict(self.later_hashes[key])
        return dict(self.hashes.get(key, {}))


class OrderFlattenScenarios:
    """Every scenario the flatten recording covers."""

    def order_entry(self, order_id, status, **overrides):
        """One entry in a broker's order book.

        Args:
            order_id (str): The broker's order id.
            status (str): The status on the shared vocabulary.
            **overrides: Fields to replace on the order.

        Returns:
            str: The entry as Redis holds it.
        """
        order = {
            'order_id': order_id,
            'status': status,
            'tradingsymbol': 'RELIANCE-flattrade',
            'instrument_token': '1',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'validity': 'DAY',
            'quantity': 10,
            'filled_quantity': 0,
            'price': 1000,
        }
        order.update(overrides)
        return json.dumps({
            'observed_at': 1790000000.0,
            'source': 'rest',
            'order': order,
            'data': {
                'norenordno': order_id,
            },
        })

    def position_entry(self, quantity, product='intraday', basis='NET', token='1'):
        """One entry in a broker's positions hash.

        Args:
            quantity (float): The net quantity, signed.
            product (str): The product on the shared vocabulary.
            basis (str): `NET` or `DAY`.
            token (str): The broker's own instrument token.

        Returns:
            str: The entry as Redis holds it.
        """
        return json.dumps({
            'observed_at': 1790000000.0,
            'position': {
                'instrument_token': token,
                'tradingsymbol': 'RELIANCE-flattrade',
                'exchange': 'NSE',
                'product': product,
                'quantity': quantity,
                'day_or_net': basis,
            },
        })

    def flatten(self, name, **settings):
        """Builds one flatten scenario.

        Args:
            name (str): The scenario name.
            **settings: The scenario's own keys.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'body': {
                'confirm': 'FLATTEN',
            },
        }
        scenario.update(settings)
        return scenario

    def accepted(self):
        """A broker answer Flattrade reads as success, for both a cancel and a place.

        Returns:
            dict: The stubbed answer.
        """
        return {
            'status': 200,
            'json': {
                'stat': 'Ok',
                'norenordno': '26091500000099',
                'result': '26091500000099',
            },
        }

    def build(self):
        """Builds every scenario, in the order the recording holds them.

        Returns:
            list: The scenarios.
        """
        open_order = {
            '26091500000021': self.order_entry('26091500000021', 'OPEN'),
        }
        cancelled_order = {
            '26091500000021': self.order_entry(
                '26091500000021',
                'CANCELLED',
            ),
        }
        long_position = {
            'RELIANCE-MIS': self.position_entry(10),
        }
        return [
            self.flatten(
                'without_the_confirmation_nothing_happens',
                body={},
            ),
            self.flatten(
                'a_wrong_confirmation_is_refused',
                body={
                    'confirm': 'flatten',
                },
            ),
            self.flatten(
                'a_dry_run_reports_and_sends_nothing',
                body={
                    'confirm': 'FLATTEN',
                    'dry_run': True,
                },
                orders=open_order,
                positions=long_position,
            ),
            self.flatten(
                'nothing_open_and_nothing_held_is_already_flat',
            ),
            self.flatten(
                'an_order_is_cancelled_before_a_position_is_closed',
                answer=self.accepted(),
                orders=open_order,
                orders_after=cancelled_order,
                positions=long_position,
            ),
            self.flatten(
                'a_short_position_is_closed_by_buying',
                answer=self.accepted(),
                positions={
                    'RELIANCE-MIS': self.position_entry(-10),
                },
            ),
            self.flatten(
                'a_cancel_that_is_never_confirmed_is_reported',
                answer=self.accepted(),
                orders=open_order,
                positions=long_position,
            ),
            self.flatten(
                'a_finished_order_is_not_cancelled',
                answer=self.accepted(),
                orders={
                    '26091500000021': self.order_entry(
                        '26091500000021',
                        'COMPLETE',
                    ),
                },
                positions=long_position,
            ),
            self.flatten(
                'a_day_position_is_left_to_its_net_row',
                positions={
                    'RELIANCE-MIS-DAY': self.position_entry(10, basis='DAY'),
                },
            ),
            self.flatten(
                'a_position_whose_token_maps_to_nothing_is_not_closed',
                positions={
                    'RELIANCE-MIS': self.position_entry(10, token='999999'),
                },
            ),
            self.flatten(
                'a_flat_position_is_left_alone',
                positions={
                    'RELIANCE-MIS': self.position_entry(0),
                },
            ),
        ]


class OrderFlattenSuite:
    """Runs every flatten scenario against the order blueprint, then records or compares the results.

    Attributes:
        fake_redis (FakeFlattenRedis): The stand-in the blueprint reads.
        network (FakeBrokerNetwork): The stubbed broker network.
    """

    def __init__(self):
        """Builds the suite with an empty stand-in and a stubbed network.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = FakeFlattenRedis()
        self.network = order_routes.FakeBrokerNetwork()

    def fake_cache(self):
        """Hands the blueprint the stand-in instead of a Redis client.

        Returns:
            FakeFlattenRedis: The current stand-in.
        """
        return self.fake_redis

    def fake_mongo_database(self):
        """Hands the blueprint no MongoDB database.

        Returns:
            None: Always None.
        """
        return None

    def fixed_uuid(self):
        """Replaces `uuid.uuid4` so generated identifiers are the same on every run.

        Returns:
            uuid.UUID: A constant identifier.
        """
        return uuid.UUID('00000000-0000-4000-8000-00000000abcd')

    def build_state(self, scenario):
        """A stand-in holding the order routes' starting contents plus this scenario's books.

        Returns:
            FakeFlattenRedis: The stand-in.
        """
        starting_state = order_routes.OrderRoutesState().build()
        fake_redis = FakeFlattenRedis()
        fake_redis.strings = starting_state.strings
        fake_redis.hashes = starting_state.hashes
        fake_redis.sorted_sets = starting_state.sorted_sets
        for broker_name in order_routes.BROKER_NAMES:
            fake_redis.hashes[f'{broker_name}:orders:orders'] = {}
            fake_redis.hashes[f'{broker_name}:portfolio:positions'] = {}
        fake_redis.hashes['flattrade:orders:orders'] = dict(
            scenario.get('orders') or {},
        )
        fake_redis.hashes['flattrade:portfolio:positions'] = dict(
            scenario.get('positions') or {},
        )
        if scenario.get('orders_after') is not None:
            fake_redis.later_hashes['flattrade:orders:orders'] = dict(
                scenario['orders_after'],
            )
        fake_redis.hashes['unified:broker_tokens'] = {
            'flattrade:1': json.dumps([
                order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[
                    'reliance'
                ],
            ]),
        }
        return fake_redis

    def build_client(self):
        """Builds a Flask test client over a fresh order blueprint.

        Returns:
            flask.testing.FlaskClient: The client.
        """
        application = flask.Flask('order_flatten_suite')
        blueprint = orders_blueprint.OrdersBlueprint()
        application.register_blueprint(
            blueprint.blueprint,
            url_prefix='/api/orders',
        )
        return application.test_client()

    def run_scenario(self, scenario):
        """Runs one scenario from fresh Redis contents and a fresh blueprint.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = self.build_state(scenario)
        self.network.reset(scenario.get('answer'))
        client = self.build_client()
        self.fake_redis.round_trips = 0

        response = client.post(
            '/api/orders/flatten',
            headers={
                'access-token': order_routes.API_TOKEN,
            },
            json=scenario['body'],
        )
        body = response.get_json(silent=True)
        if isinstance(body, dict) and isinstance(body.get('timing_ms'), dict):
            body['timing_ms'] = sorted(body['timing_ms'])
        return {
            'name': scenario['name'],
            'status': response.status_code,
            'body': body,
            'sent': [
                {
                    'method': sent['method'],
                    'url': sent['url'],
                }
                for sent in copy.deepcopy(self.network.sent_requests)
            ],
            'redis_round_trips': self.fake_redis.round_trips,
        }

    def run_every_scenario(self):
        """Runs every scenario with Redis, MongoDB, the broker network and `uuid.uuid4` replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_get_cache = blueprint_base.get_cache
        original_get_mongo_database = blueprint_base.get_mongo_db
        original_request = requests.Session.request
        original_uuid4 = uuid.uuid4
        original_wait = api_configuration['order_flatten_wait_seconds']
        original_placement = api_configuration['order_placement']
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_mongo_database
        requests.Session.request = self.network.request
        uuid.uuid4 = self.fixed_uuid
        # Long enough for one more read of the books, short enough that a cancel nobody confirms
        # does not hold the suite up.
        api_configuration['order_flatten_wait_seconds'] = 0.6
        api_configuration['order_placement'] = 'direct'
        try:
            results = []
            for scenario in OrderFlattenScenarios().build():
                results.append(self.run_scenario(scenario))
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            api_configuration['order_flatten_wait_seconds'] = original_wait
            api_configuration['order_placement'] = original_placement
        return results

    def encode(self, result):
        """Encodes one result as a single stable line of JSON.

        Args:
            result (dict): The result.

        Returns:
            str: The JSON line, with sorted keys.
        """
        return json.dumps(result, sort_keys=True, ensure_ascii=False)

    def record(self, results):
        """Writes the results to the fixture file, one scenario per line.

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
        """Reads the fixture file.

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

    def compare(self, results):
        """Compares the results with the fixture file and prints every difference.

        Args:
            results (list): The results.

        Returns:
            int: The exit code: 0 when everything matches, 1 otherwise.
        """
        if not FIXTURE_PATH.exists():
            print(f'no recording at {FIXTURE_PATH}; run with --record first')
            return 1
        recorded = self.read_recording()
        failures = 0
        current_names = set()
        for result in results:
            current_names.add(result['name'])
            expected = recorded.get(result['name'])
            if expected is None:
                failures = failures + 1
                print(f'NEW      {result["name"]}')
                print(f'  now:      {self.encode(result)}')
            elif self.encode(expected) != self.encode(result):
                failures = failures + 1
                print(f'CHANGED  {result["name"]}')
                print(f'  recorded: {self.encode(expected)}')
                print(f'  now:      {self.encode(result)}')
        for name in recorded:
            if name not in current_names:
                failures = failures + 1
                print(f'MISSING  {name}')
        passed = len(results) - failures
        print(f'{passed} of {len(results)} scenarios match the recording, {failures} differ')
        if failures:
            return 1
        return 0

    def run(self):
        """Runs the suite from the command line.

        Returns:
            int: The exit code.
        """
        parser = argparse.ArgumentParser(
            description='Check POST /api/orders/flatten against its recorded behaviour.',
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
    sys.exit(OrderFlattenSuite().run())
