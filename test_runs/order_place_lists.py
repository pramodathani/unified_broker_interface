"""Offline check of the list form of `POST /api/orders/place` and of `GET /api/orders/intents/<intent_id>` against a recording of their behaviour.

Runs the routes in-process through Flask's test client with bodies that hold an `orders` list. Redis, the starting instruments, logins and settings, the broker network and the real order engine behind the place route all come from `test_runs/order_routes.py`, so a list is checked against exactly the orders the single form is. Every stub broker answers a placement with its own recorded success body, so a list spread across brokers is accepted at each of them.

For each scenario it keeps the HTTP status, the response body, the broker requests that went out and the number of Redis round trips, and compares them with `test_runs/fixtures/order_place_lists.jsonl`. The recording is a separate file, because `--record` rewrites a whole fixture and `order_routes.jsonl` is the evidence that the single form did not change.

No Redis, database, credentials or network are used, and no request leaves the process.

Typical usage:

    python -m test_runs.order_place_lists
    python -m test_runs.order_place_lists --record
"""

import argparse
import copy
import json
import pathlib
import sys
import urllib.parse
import uuid

import requests

from test_runs import order_change_lists
from test_runs import order_routes
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.utilities.broker_orders.utilities.registry import (
    BROKER_ORDER_CLASSES,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY as ENGINE_LOCK_KEY,
)
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / 'fixtures'
    / 'order_place_lists.jsonl'
)
KOTAK_HOST = 'kotaksecurities.com'
RELIANCE = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']


class OrderPlaceListScenarios:
    """Builds every list scenario, in the order they are recorded.

    Attributes:
        bodies (order_routes.OrderRoutesScenarios): The order routes' body builders.
    """

    def __init__(self):
        """Builds the scenario set.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = order_routes.OrderRoutesScenarios()

    def place(self, name, body, **settings):
        """Builds one list placement scenario.

        Args:
            name (str): The scenario name.
            body (object): The request body.
            **settings: Other scenario keys, such as `engine_stopped`, `maximum`, or `then_read_intent` to read the first answer back through `GET /api/orders/intents/<intent_id>` afterwards.

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

    def plain(self, **overrides):
        """One plain MARKET order for ten RELIANCE shares, sent rather than dry-run.

        Args:
            **overrides: Body fields to replace or add.

        Returns:
            dict: The order.
        """
        body = self.bodies.market_order(dry_run=None)
        body.update(overrides)
        return body

    def build(self):
        """Builds every scenario.

        Returns:
            list: The scenarios.
        """
        ladder = self.plain(
            order_type='LIMIT',
            price=1000,
            quantity=20,
            synthetic={
                'type': 'ladder',
                'from_price': 995,
                'to_price': 1000,
                'steps': 2,
            },
        )
        return [
            self.place(
                'three_plain_orders_go_to_three_brokers_in_turn',
                {
                    'orders': [
                        self.plain(),
                        self.plain(),
                        self.plain(),
                    ],
                },
            ),
            self.place(
                'a_dry_run_list_shows_every_request_and_sends_none',
                {
                    'orders': [
                        self.plain(),
                        self.plain(),
                    ],
                    'dry_run': True,
                },
            ),
            self.place(
                'a_synthetic_order_and_a_plain_one_in_one_list',
                {
                    'orders': [
                        ladder,
                        self.plain(),
                    ],
                },
            ),
            self.place(
                'invalid_and_unmapped_items_are_refused_on_their_own',
                {
                    'orders': [
                        self.plain(quantity=-5),
                        self.plain(instrument_id='99999999-9999-5999-8999-999999999999'),
                        'not an order',
                        self.plain(dry_run=True),
                        self.plain(),
                    ],
                },
            ),
            self.place(
                'a_broker_named_in_an_item_is_ignored',
                {
                    'orders': [
                        self.plain(broker='zerodha'),
                    ],
                },
            ),
            self.place(
                'an_empty_list_is_refused',
                {
                    'orders': [],
                },
            ),
            self.place(
                'a_list_longer_than_the_maximum_is_refused',
                {
                    'orders': [
                        self.plain(),
                        self.plain(),
                        self.plain(),
                    ],
                },
                maximum=2,
            ),
            self.place(
                'a_key_other_than_orders_and_dry_run_is_refused',
                {
                    'orders': [
                        self.plain(),
                    ],
                    'tag': 'listTag',
                },
            ),
            self.place(
                'a_list_is_refused_whole_when_the_engine_is_not_running',
                {
                    'orders': [
                        self.plain(),
                    ],
                },
                engine_stopped=True,
            ),
            self.place(
                'a_placed_order_can_be_read_back_by_its_intent_id',
                {
                    'orders': [
                        self.plain(),
                    ],
                },
                then_read_intent=True,
            ),
            self.place(
                'an_unknown_intent_id_is_not_found',
                None,
                read_intent_only='00000000000000000000000000000000',
            ),
        ]


class OrderPlaceListSuite(order_routes.OrderRoutesSuite):
    """Runs the list scenarios through the order suite's machinery, and records or compares them in their own fixture.

    Attributes:
        current_scenario (dict): The scenario being run, which decides whether the engine's lock is taken.
        last_client (flask.testing.FlaskClient | None): The client the last scenario built, for reading an answer back afterwards.
    """

    def __init__(self):
        """Builds the suite with the per-URL network stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.network = order_change_lists.ListBrokerNetwork()
        self.current_scenario = {}
        self.last_client = None

    def place_answers(self):
        """Each broker's own success body for a placement, chosen by its API host.

        Returns:
            dict: The network's answer setting, with `by_url` pairs of host and answer.
        """
        answers = order_routes.OrderRoutesAnswers()
        by_url = []
        for broker_order_class in BROKER_ORDER_CLASSES:
            host = KOTAK_HOST
            if broker_order_class.WARM_URL:
                host = urllib.parse.urlsplit(broker_order_class.WARM_URL).hostname
            by_url.append([
                host,
                answers.json_answer(
                    200,
                    answers.place_success(broker_order_class.BROKER_NAME),
                ),
            ])
        return {
            'by_url': by_url,
        }

    def run_list_scenario(self, scenario):
        """Runs one list scenario, then reads the first answer back by its intent id when the scenario asks to.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        original_maximum = api_configuration['order_place_list_maximum']
        api_configuration['order_place_list_maximum'] = scenario.get(
            'maximum',
            original_maximum,
        )
        api_configuration['order_hold_limits'] = scenario.get('hold_limits', False)
        try:
            request = dict(scenario)
            request['answer'] = self.place_answers()
            if scenario.get('read_intent_only'):
                self.fake_redis = self.build_state()
                self.counting_uuid.reset()
                client = self.build_client()
                result = self.read_intent(client, scenario['read_intent_only'])
                result['name'] = scenario['name']
                return result
            result = self.run_scenario(request)
            if scenario.get('then_read_intent'):
                results = result['body']['results']
                intent_id = results[0]['intent_id']
                result['read_back'] = self.read_intent(self.last_client, intent_id)
            return result
        finally:
            api_configuration['order_place_list_maximum'] = original_maximum

    def build_client(self):
        """Builds a Flask test client over a fresh order blueprint, keeping it for a later read.

        Returns:
            flask.testing.FlaskClient: The client.
        """
        client = super().build_client()
        self.last_client = client
        return client

    def build_state(self):
        """Builds the starting stand-in, without the engine's lock when the current scenario stops the engine.

        Returns:
            redis_stand_ins.InlineEngineRedis: The stand-in.
        """
        fake_redis = super().build_state()
        if self.current_scenario.get('engine_stopped'):
            fake_redis.strings.pop(ENGINE_LOCK_KEY, None)
        return fake_redis

    def read_intent(self, client, intent_id):
        """Reads one stored answer through `GET /api/orders/intents/<intent_id>`.

        Args:
            client (flask.testing.FlaskClient): The client over the blueprint under test.
            intent_id (str): The intent's id.

        Returns:
            dict: The status and the response body.
        """
        response = client.get(
            f'/api/orders/intents/{intent_id}',
            headers={
                'access-token': order_routes.API_TOKEN,
            },
        )
        body = response.get_json(silent=True)
        if isinstance(body, dict):
            answer_body = body.get('response')
            if isinstance(answer_body, dict) and isinstance(answer_body.get('timing_ms'), dict):
                answer_body['timing_ms'] = sorted(answer_body['timing_ms'])
        return {
            'status': response.status_code,
            'body': body,
        }

    def send(self, client, request):
        """Sends one scenario request and records the list's results in a stable form.

        Args:
            client (flask.testing.FlaskClient): The client over the blueprint under test.
            request (dict): The scenario request.

        Returns:
            dict: The status, the response body, the broker requests sorted, and the Redis round trips.
        """
        result = super().send(client, request)
        result['sent'] = sorted(result['sent'], key=self.request_sort_key)
        body = result['body']
        if isinstance(body, dict) and isinstance(body.get('results'), list):
            for entry in body['results']:
                response = entry.get('response')
                if isinstance(response, dict) and isinstance(response.get('timing_ms'), dict):
                    response['timing_ms'] = sorted(response['timing_ms'])
        return result

    def request_sort_key(self, sent_request):
        """The key captured requests are sorted by, since a list's orders leave in no fixed order.

        Args:
            sent_request (dict): One captured request.

        Returns:
            str: The request as JSON with sorted keys.
        """
        return json.dumps(sent_request, sort_keys=True, default=str)

    def run_every_scenario(self):
        """Runs every list scenario with Redis, MongoDB, the broker network and `uuid.uuid4` replaced.

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
            results = []
            for scenario in OrderPlaceListScenarios().build():
                self.current_scenario = scenario
                results.append(self.run_list_scenario(scenario))
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            api_configuration.update(original_settings)
        return results

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
            description='Check the list form of the place route against its recorded behaviour.',
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
    sys.exit(OrderPlaceListSuite().run())
