"""Offline check of the list form of `PUT /api/orders/modify` and `DELETE /api/orders/cancel` against a recording of its behaviour.

Runs the two routes in-process through Flask's test client with bodies that hold an `orders` list. Redis, the starting order books, logins and settings, and the broker network all come from `test_runs/order_routes.py`, so a list is checked against exactly the orders the single form is. The network stand-in is widened so a scenario can answer different brokers differently.

For each scenario it keeps the HTTP status, the response body, the broker requests that went out and the number of Redis round trips, and compares them with `test_runs/fixtures/order_change_lists.jsonl`. A list sends its requests on several threads, so the requests that went out are recorded sorted rather than in the order they happened to leave.

The recording is deliberately a separate file, because `--record` rewrites a whole fixture and `order_routes.jsonl` is the evidence that the single form did not change.

No Redis, database, credentials or network are used, and no request leaves the process. The project's `.env` still has to exist, because importing the blueprint imports `utilities.configurations`.

Typical usage:

    python -m test_runs.order_change_lists
    python -m test_runs.order_change_lists --record
"""

import argparse
import copy
import json
import pathlib
import sys
import threading
import uuid

import requests

from test_runs import order_routes
from unified_broker_interface.blueprints import base as blueprint_base
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / 'fixtures'
    / 'order_change_lists.jsonl'
)
ORDER_IDENTIFIERS = order_routes.OrderRoutesState.ORDER_IDENTIFIERS
SUCCESS_ANSWER = {
    'status': 200,
    'json': {
        'status': 'success',
        'stat': 'Ok',
        's': 'ok',
        'type': 'success',
    },
}
REFUSAL_ANSWER = {
    'status': 400,
    'json': {
        'errorMessage': 'bad request',
    },
}


class ListBrokerNetwork(order_routes.FakeBrokerNetwork):
    """The order routes' network stand-in, answering each request by the first URL fragment it contains.

    A list sends to several brokers from several threads, so the answer is chosen per request rather than held as one shared answer, and captured requests are appended under a lock.

    Attributes:
        answers_by_url (list): `(URL fragment, answer)` pairs, tried in order.
        default_answer (dict): The answer for a request no fragment matches.
    """

    def __init__(self):
        """Builds the network answering every request with success.

        Returns:
            None: This method returns nothing.
        """
        self.answers_by_url = []
        self.default_answer = SUCCESS_ANSWER
        self._lock = threading.Lock()
        super().__init__()

    def reset(self, answer):
        """Clears the captured requests and sets the answers for the next calls.

        Args:
            answer (dict | None): None for success everywhere, or a dictionary with `default` (an answer) and `by_url` (a list of `[URL fragment, answer]` pairs).

        Returns:
            None: This method returns nothing.
        """
        self.sent_requests = []
        self.answers_by_url = []
        self.default_answer = SUCCESS_ANSWER
        if answer is None:
            return
        self.default_answer = answer.get('default', SUCCESS_ANSWER)
        for fragment, fragment_answer in answer.get('by_url', []):
            self.answers_by_url.append((fragment, fragment_answer))

    def request(self, method, url, **keyword_arguments):
        """Captures one outgoing request and answers it by its URL.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments: The remaining `requests` arguments.

        Returns:
            order_routes.FakeResponse: The stubbed answer.

        Raises:
            requests.exceptions.ConnectTimeout: When the chosen answer names `ConnectTimeout`.
        """
        timeout = keyword_arguments.get('timeout')
        if timeout is not None:
            timeout = list(timeout)
        with self._lock:
            self.sent_requests.append({
                'method': method,
                'url': url,
                'params': keyword_arguments.get('params'),
                'data': keyword_arguments.get('data'),
                'json': keyword_arguments.get('json'),
                'headers': keyword_arguments.get('headers'),
                'timeout': timeout,
                'verify': keyword_arguments.get('verify'),
            })
        answer = self.default_answer
        for fragment, fragment_answer in self.answers_by_url:
            if fragment in url:
                answer = fragment_answer
                break
        if answer.get('raise') == 'ConnectTimeout':
            raise requests.exceptions.ConnectTimeout('stubbed connect timeout')
        return order_routes.FakeResponse(
            answer['status'],
            json_body=answer.get('json'),
            text=answer.get('text'),
        )


class OrderChangeListScenarios:
    """Builds every list scenario, in the order they are recorded."""

    def cancel(self, name, body, **settings):
        """Builds one cancel scenario.

        Args:
            name (str): The scenario name.
            body (object): The request body.
            **settings: Other scenario keys, such as `query`, `answer`, `headers` or `failing_round_trip`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'route': 'cancel',
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def modify(self, name, body, **settings):
        """Builds one modify scenario.

        Args:
            name (str): The scenario name.
            body (object): The request body.
            **settings: Other scenario keys, such as `query`, `answer`, `headers` or `failing_round_trip`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'route': 'modify',
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def every_open_order(self, **fields):
        """Builds one list item per broker, naming that broker's open order.

        Args:
            **fields: Fields every item carries, such as `price` for a modify.

        Returns:
            list: The items, in broker order.
        """
        items = []
        for broker_name in order_routes.BROKER_NAMES:
            item = {
                'order_id': ORDER_IDENTIFIERS[broker_name],
            }
            item.update(fields)
            items.append(item)
        return items

    def build(self):
        """Builds every scenario.

        Returns:
            list: The scenarios.
        """
        scenarios = []
        scenarios.extend(self.cancel_scenarios())
        scenarios.extend(self.cancel_refusal_scenarios())
        scenarios.extend(self.modify_scenarios())
        return scenarios

    def cancel_scenarios(self):
        """Builds the cancel lists that reach brokers or show what they would send.

        Returns:
            list: The scenarios.
        """
        zerodha_order = ORDER_IDENTIFIERS['zerodha']
        dhan_order = ORDER_IDENTIFIERS['dhan']
        many_unknown = []
        for index in range(60):
            many_unknown.append({
                'order_id': f'NOSUCHORDER{index}',
            })
        return [
            self.cancel('cancel_list_every_broker', {'orders': self.every_open_order()}),
            self.cancel(
                'cancel_list_every_broker_dry_run',
                {
                    'orders': self.every_open_order(),
                    'dry_run': True,
                },
            ),
            self.cancel(
                'cancel_list_dry_run_in_query',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                    ],
                },
                query={
                    'dry_run': 'true',
                },
            ),
            self.cancel(
                'cancel_list_of_one',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                    ],
                },
            ),
            self.cancel(
                'cancel_list_every_kind_of_entry',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                        {
                            'order_id': '250915000000099',
                        },
                        {
                            'order_id': 'NOSUCHORDER',
                        },
                        'not an object',
                        {
                            'order_id': dhan_order,
                            'dry_run': True,
                        },
                        {
                            'order_id': zerodha_order,
                            'broker': 'zerodha',
                        },
                        {},
                        {
                            'order_id': '26091500099999',
                        },
                        {
                            'order_id': dhan_order,
                        },
                    ],
                },
            ),
            self.cancel(
                'cancel_list_same_id_at_two_named_brokers',
                {
                    'orders': [
                        {
                            'order_id': '26091500099999',
                            'broker': 'flattrade',
                        },
                        {
                            'order_id': '26091500099999',
                            'broker': 'shoonya',
                        },
                    ],
                    'dry_run': True,
                },
            ),
            self.cancel(
                'cancel_list_one_broker_refuses',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                        {
                            'order_id': dhan_order,
                        },
                    ],
                },
                answer={
                    'by_url': [
                        [
                            'dhan.co',
                            REFUSAL_ANSWER,
                        ],
                    ],
                },
            ),
            self.cancel(
                'cancel_list_every_connection_times_out',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                        {
                            'order_id': dhan_order,
                        },
                    ],
                },
                answer={
                    'default': {
                        'raise': 'ConnectTimeout',
                    },
                },
            ),
            self.cancel('cancel_list_sixty_unknown_orders_one_round_trip', {'orders': many_unknown}),
        ]

    def cancel_refusal_scenarios(self):
        """Builds the cancel lists refused as a whole.

        Returns:
            list: The scenarios.
        """
        zerodha_order = ORDER_IDENTIFIERS['zerodha']
        one_order = {
            'orders': [
                {
                    'order_id': zerodha_order,
                },
            ],
        }
        return [
            self.cancel('cancel_list_not_a_list', {'orders': zerodha_order}),
            self.cancel('cancel_list_empty', {'orders': []}),
            self.cancel(
                'cancel_list_with_broker_beside_it',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                    ],
                    'broker': 'zerodha',
                },
            ),
            self.cancel('cancel_list_with_order_id_in_query', one_order, query={'order_id': zerodha_order}),
            self.cancel(
                'cancel_list_dry_run_invalid',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                    ],
                    'dry_run': 'maybe',
                },
            ),
            self.cancel('cancel_list_token_missing', one_order, headers={}),
            self.cancel(
                'cancel_list_token_wrong',
                one_order,
                headers={
                    'access-token': 'wrong-token',
                },
            ),
            self.cancel('cancel_list_redis_fails', one_order, failing_round_trip=1),
        ]

    def modify_scenarios(self):
        """Builds the modify lists.

        Returns:
            list: The scenarios.
        """
        zerodha_order = ORDER_IDENTIFIERS['zerodha']
        dhan_order = ORDER_IDENTIFIERS['dhan']
        return [
            self.modify('modify_list_every_broker', {'orders': self.every_open_order(price='2501.5')}),
            self.modify(
                'modify_list_every_broker_dry_run',
                {
                    'orders': self.every_open_order(
                        quantity=20,
                        price='2501.5',
                    ),
                    'dry_run': True,
                },
            ),
            self.modify(
                'modify_list_every_kind_of_entry',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                            'price': 2501,
                        },
                        {
                            'order_id': zerodha_order,
                        },
                        {
                            'order_id': dhan_order,
                            'quantity': 1.5,
                        },
                        {
                            'order_id': '250915000000099',
                            'price': 2501,
                        },
                        {
                            'order_id': 'NOSUCHORDER',
                            'price': 2501,
                        },
                        {
                            'order_id': zerodha_order,
                            'price': 2502,
                        },
                        {
                            'order_id': dhan_order,
                            'price': '2501.5',
                        },
                    ],
                },
            ),
            self.modify(
                'modify_list_one_broker_refuses',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                            'price': 2501,
                        },
                        {
                            'order_id': dhan_order,
                            'price': '2501.5',
                        },
                    ],
                },
                answer={
                    'by_url': [
                        [
                            'dhan.co',
                            REFUSAL_ANSWER,
                        ],
                    ],
                },
            ),
            self.modify(
                'modify_list_with_price_beside_it',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                        },
                    ],
                    'price': 2501,
                },
            ),
            self.modify(
                'modify_list_token_wrong',
                {
                    'orders': [
                        {
                            'order_id': zerodha_order,
                            'price': 2501,
                        },
                    ],
                },
                headers={
                    'access-token': 'wrong-token',
                },
            ),
        ]


class OrderChangeListSuite(order_routes.OrderRoutesSuite):
    """Runs the list scenarios through the order suite's machinery, and records or compares them in their own fixture."""

    def __init__(self):
        """Builds the suite with the widened network stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.network = ListBrokerNetwork()

    def send(self, client, request):
        """Sends one scenario request and records what went out in a stable order.

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
        """The key captured requests are sorted by.

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
        uuid.uuid4 = self.fixed_uuid
        try:
            results = []
            for scenario in OrderChangeListScenarios().build():
                results.append(self.run_scenario(scenario))
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

    def compare(self, results):
        """Compares the results with this suite's fixture file and prints every difference.

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
            description='Check the list form of modify and cancel against its recorded behaviour.',
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
    sys.exit(OrderChangeListSuite().run())
