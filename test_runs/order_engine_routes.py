"""Offline check of `POST /api/orders/place` in engine mode against a recording of its behaviour.

Runs the place route in-process through Flask's test client with `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` set to `engine`, so the route writes the order to a Redis stream and waits for an answer instead of calling a broker. Redis is replaced by the same in-memory stand-in `test_runs/order_routes.py` uses, widened with the stream and list commands the handoff needs, and the engine is replaced by an answer seeded onto the reply list before the request is sent.

For each scenario it keeps the HTTP status, the response body, the intents that reached the stream and the number of Redis round trips, and compares them with `test_runs/fixtures/order_engine_routes.jsonl`.

The recording is deliberately a second file. `--record` rewrites a whole fixture, so recording these scenarios into `order_routes.jsonl` would silently rewrite the recording that proves the direct path never changed.

No Redis, database, credentials or network are used, and no request leaves the process. The project's `.env` still has to exist, because importing the blueprint imports `utilities.configurations`.

Typical usage:

    python -m test_runs.order_engine_routes
    python -m test_runs.order_engine_routes --record
"""

import argparse
import copy
import json
import pathlib
import sys
import uuid

import flask
import requests

from test_runs import order_routes
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints import orders as orders_blueprint
from unified_broker_interface.utilities.order_engine.utilities import engine_lock
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / 'fixtures'
    / 'order_engine_routes.jsonl'
)
UNRECORDED_INTENT_FIELDS = [
    'api_worker',
    'created_at',
    'deadline_at',
]


class FakeEngineRedis(order_routes.FakeRedis):
    """The order routes' stand-in, widened with the stream and list commands the handoff uses.

    `blpop` never blocks: it answers with whatever was seeded onto the reply list, or with None, which is what a real wait that ran out of time returns. A scenario therefore exercises the timeout path without waiting for it.

    Attributes:
        streams (dict): Stream keys to lists of `(entry_id, fields)`.
        lists (dict): List keys to their entries.
    """

    def __init__(self):
        """Builds an empty stand-in with no streams and no lists.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.streams = {}
        self.lists = {}

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Appends one entry to a stream in its own round trip.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.
            maxlen (int | None): Accepted for compatibility with redis-py and ignored, since nothing here writes enough entries to trim.
            approximate (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            str: The entry's id.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del maxlen, approximate
        self.start_round_trip()
        entries = self.streams.setdefault(key, [])
        entry_id = f'{len(entries) + 1}-0'
        entries.append((entry_id, dict(fields)))
        return entry_id

    def blpop(self, key, timeout=None):
        """Takes the first entry off a list, answering None when there is none.

        Args:
            key (str): The list key.
            timeout (float | None): Accepted for compatibility with redis-py and ignored, since the stand-in never waits.

        Returns:
            tuple | None: `(key, value)` when the list held something, and None when it did not.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del timeout
        self.start_round_trip()
        entries = self.lists.get(key)
        if not entries:
            return None
        value = entries.pop(0)
        if not entries:
            self.lists.pop(key, None)
        return key, value


class OrderEngineScenarios:
    """Every engine-mode scenario the recording covers.

    Attributes:
        bodies (OrderRoutesScenarios): The order routes' own body builders, reused so an engine-mode order is the same order the direct path was recorded with.
    """

    def __init__(self):
        """Builds the scenario set.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = order_routes.OrderRoutesScenarios()

    def accepted_answer(self):
        """The answer the engine pushes for an order a broker accepted.

        Returns:
            dict: The reply document.
        """
        return {
            'body': {
                'broker': 'zerodha',
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'tag': 'engineTag',
                'outcome': 'accepted',
                'order_id': '240925000000001',
                'status_message': None,
                'broker_response': {
                    'status': 'success',
                },
                'skipped': [],
                'timing_ms': {
                    'preparation': 0.4,
                    'broker': 120.5,
                },
            },
            'status': 200,
        }

    def rejected_answer(self):
        """The answer the engine pushes for an order a broker refused.

        Returns:
            dict: The reply document.
        """
        return {
            'body': {
                'broker': 'dhan',
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'tag': None,
                'outcome': 'rejected',
                'order_id': None,
                'status_message': 'DH-906 Market is Closed!',
                'broker_response': {
                    'errorCode': 'DH-906',
                },
                'skipped': [],
                'timing_ms': {
                    'preparation': 0.6,
                    'broker': 88.25,
                },
            },
            'status': 422,
        }

    def refusal_answer(self):
        """The answer the engine pushes when it refuses the order without calling a broker.

        Returns:
            dict: The reply document.
        """
        return {
            'body': {
                'error': 'no broker can take this order',
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'skipped': [],
            },
            'status': 503,
        }

    def dry_run_answer(self):
        """The answer the engine pushes for a dry run, which carries no broker time.

        Returns:
            dict: The reply document.
        """
        return {
            'body': {
                'broker': 'zerodha',
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'tag': None,
                'dry_run': True,
                'request': {
                    'method': 'POST',
                    'url': 'https://api.kite.trade/orders/regular',
                },
                'skipped': [],
                'timing_ms': {
                    'preparation': 0.3,
                },
            },
            'status': 200,
        }

    def place(self, name, body, **settings):
        """Builds one engine-mode place scenario.

        Args:
            name (str): The scenario name.
            body (dict | None): The request body.
            **settings: Any other scenario keys, such as `reply`, `headers`, `failing_round_trip` or `engine_running` (False to leave the engine's lock unset).

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'route': 'place',
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def build(self):
        """Builds every scenario, in the order the recording holds them.

        Returns:
            list: The scenarios.
        """
        return [
            self.place(
                'engine_accepts_a_sent_order',
                self.bodies.market_order(dry_run=None, tag='engineTag'),
                reply=self.accepted_answer(),
            ),
            self.place(
                'engine_reports_a_broker_refusal',
                self.bodies.market_order(dry_run=None),
                reply=self.rejected_answer(),
            ),
            self.place(
                'engine_refusal_keeps_its_status',
                self.bodies.market_order(dry_run=None),
                reply=self.refusal_answer(),
            ),
            self.place(
                'engine_answers_a_dry_run',
                self.bodies.market_order(),
                reply=self.dry_run_answer(),
            ),
            self.place(
                'engine_never_answers',
                self.bodies.market_order(dry_run=None, tag='lostTag'),
            ),
            self.place(
                'engine_not_running_is_refused_before_the_intent_is_written',
                self.bodies.market_order(dry_run=None),
                engine_running=False,
            ),
            self.place(
                'engine_answer_is_not_json',
                self.bodies.market_order(dry_run=None),
                raw_reply='not json at all',
            ),
            self.place(
                'engine_answer_carries_no_body',
                self.bodies.market_order(dry_run=None),
                raw_reply=json.dumps({
                    'status': 200,
                }),
            ),
            self.place(
                'engine_answer_carries_no_status',
                self.bodies.market_order(dry_run=None),
                raw_reply=json.dumps({
                    'body': {
                        'outcome': 'accepted',
                        'order_id': '1',
                    },
                }),
            ),
            self.place(
                'identity_fields_are_resolved_before_the_intent_is_written',
                self.bodies.by_fields(
                    'nse',
                    'equities',
                    symbol='RELIANCE',
                    dry_run=None,
                ),
                reply=self.accepted_answer(),
            ),
            self.place(
                'unknown_identity_fields_are_never_queued',
                self.bodies.by_fields(
                    'nse',
                    'equities',
                    symbol='NOTLISTED',
                    dry_run=None,
                ),
            ),
            self.place(
                'an_invalid_body_is_never_queued',
                self.bodies.market_order(quantity=0),
            ),
            self.place(
                'a_bad_token_is_never_queued',
                self.bodies.market_order(),
                headers={
                    'access-token': 'wrong',
                },
            ),
            self.place(
                'the_engine_lock_cannot_be_read',
                self.bodies.market_order(dry_run=None),
                failing_round_trip=2,
            ),
            self.place(
                'the_intent_cannot_be_written',
                self.bodies.market_order(dry_run=None),
                failing_round_trip=3,
            ),
            self.place(
                'the_answer_cannot_be_read',
                self.bodies.market_order(dry_run=None),
                failing_round_trip=4,
            ),
            self.place(
                'a_synthetic_type_reaches_the_engine',
                self.bodies.market_order(
                    dry_run=None,
                    synthetic={
                        'type': 'bracket',
                        'stop_loss': 1200,
                    },
                ),
                reply=self.accepted_answer(),
            ),
            self.place(
                'direct_mode_writes_no_intent',
                self.bodies.market_order(),
                placement='direct',
            ),
            self.place(
                'an_unknown_placement_mode_stops_the_worker',
                None,
                placement='engin',
                expect_construction_error=True,
            ),
        ]


class OrderEngineRoutesSuite:
    """Runs every engine-mode scenario against the order blueprint, then records or compares the results.

    Attributes:
        fake_redis (FakeEngineRedis): The stand-in the blueprint under test reads.
        network (FakeBrokerNetwork): The stubbed broker network, which nothing should reach in engine mode.
    """

    def __init__(self):
        """Builds the suite with an empty stand-in and a stubbed network.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = FakeEngineRedis()
        self.network = order_routes.FakeBrokerNetwork()

    def fake_cache(self):
        """Hands the blueprint the stand-in instead of a Redis client.

        Returns:
            FakeEngineRedis: The current stand-in.
        """
        return self.fake_redis

    def fake_mongo_database(self):
        """Hands the blueprint no MongoDB database, since the order routes never read it.

        Returns:
            None: Always None.
        """
        return None

    def fixed_uuid(self):
        """Replaces `uuid.uuid4` so an intent's id is the same on every run.

        Returns:
            uuid.UUID: A constant identifier.
        """
        return uuid.UUID('00000000-0000-4000-8000-00000000abcd')

    def build_state(self):
        """Builds a stand-in holding the order routes' starting contents, with streams and lists added.

        Returns:
            FakeEngineRedis: The stand-in.
        """
        starting_state = order_routes.OrderRoutesState().build()
        fake_redis = FakeEngineRedis()
        fake_redis.strings = starting_state.strings
        fake_redis.hashes = starting_state.hashes
        fake_redis.sorted_sets = starting_state.sorted_sets
        return fake_redis

    def build_client(self):
        """Builds a Flask test client over a fresh order blueprint.

        Returns:
            flask.testing.FlaskClient: The client.
        """
        application = flask.Flask('order_engine_routes_suite')
        blueprint = orders_blueprint.OrdersBlueprint()
        application.register_blueprint(
            blueprint.blueprint,
            url_prefix='/api/orders',
        )
        return application.test_client()

    def seed_reply(self, scenario):
        """Puts the answer the engine would have pushed onto the reply list before the request is sent.

        The reply key names the intent, and the intent is not built until the request runs, but `uuid.uuid4` is fixed for the whole run, so the key is known in advance.

        Args:
            scenario (dict): The scenario.

        Returns:
            None: This method returns nothing.
        """
        raw_reply = scenario.get('raw_reply')
        if raw_reply is None:
            reply = scenario.get('reply')
            if reply is None:
                return
            raw_reply = json.dumps(reply)
        reply_key = 'unified:orders:intents:result:' + self.fixed_uuid().hex
        self.fake_redis.lists[reply_key] = [
            raw_reply,
        ]

    def shown_intents(self):
        """The intents that reached the stream, with the fields that differ between runs left out.

        `created_at` and `deadline_at` are clock readings and `api_worker` names this host and process, so none of the three can be recorded. What they are for is still checked: the gap between the two times is recorded as `timeout_seconds`, which must match the configured wait.

        Returns:
            list: One dictionary per intent written.
        """
        shown = []
        entries = self.fake_redis.streams.get(
            'unified:orders:intents:stream',
            [],
        )
        for _, fields in entries:
            document = json.loads(fields['intent'])
            kept = {}
            for name, value in document.items():
                if name not in UNRECORDED_INTENT_FIELDS:
                    kept[name] = value
            kept['timeout_seconds'] = round(
                document['deadline_at'] - document['created_at'],
                3,
            )
            kept['unrecorded'] = sorted(UNRECORDED_INTENT_FIELDS)
            shown.append(kept)
        return shown

    def open_request(self, client, scenario):
        """Sends one scenario's request through the test client.

        Args:
            client (flask.testing.FlaskClient): The client over the blueprint under test.
            scenario (dict): The scenario.

        Returns:
            werkzeug.test.TestResponse: The response.
        """
        headers = scenario.get('headers')
        if headers is None:
            headers = {
                'access-token': order_routes.API_TOKEN,
            }
        return client.open(
            '/api/orders/place',
            method='POST',
            headers=headers,
            json=scenario['body'],
        )

    def run_scenario(self, scenario):
        """Runs one scenario from fresh Redis contents and a fresh blueprint.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = self.build_state()
        if scenario.get('engine_running', True):
            self.fake_redis.strings[engine_lock.LOCK_KEY] = 'engine-process'
        api_configuration['order_placement'] = scenario.get(
            'placement',
            'engine',
        )
        if scenario.get('expect_construction_error'):
            try:
                self.build_client()
            except ValueError as error:
                return {
                    'name': scenario['name'],
                    'construction_error': str(error),
                }
            return {
                'name': scenario['name'],
                'construction_error': None,
            }
        client = self.build_client()
        self.network.reset(None)
        self.seed_reply(scenario)
        self.fake_redis.round_trips = 0
        self.fake_redis.failing_round_trip = scenario.get('failing_round_trip')

        response = self.open_request(client, scenario)

        body = response.get_json(silent=True)
        if isinstance(body, dict) and isinstance(body.get('timing_ms'), dict):
            body['timing_ms'] = sorted(body['timing_ms'])
        return {
            'name': scenario['name'],
            'status': response.status_code,
            'body': body,
            'intents': self.shown_intents(),
            'sent': copy.deepcopy(self.network.sent_requests),
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
        original_placement = api_configuration['order_placement']
        original_excluded = api_configuration['order_excluded_brokers']
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_mongo_database
        requests.Session.request = self.network.request
        uuid.uuid4 = self.fixed_uuid
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        try:
            results = []
            for scenario in OrderEngineScenarios().build():
                results.append(self.run_scenario(scenario))
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            api_configuration['order_placement'] = original_placement
            api_configuration['order_excluded_brokers'] = original_excluded
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
            description='Check the place route in engine mode against its recorded behaviour.',
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
    sys.exit(OrderEngineRoutesSuite().run())
