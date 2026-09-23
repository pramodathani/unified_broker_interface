"""Offline check of `bin/unified/orders/order_engine` against a recording of its behaviour.

Drives the engine's own classes with scripted intents, Redis replaced by an in-memory stand-in and every broker call answered by a stub. For each scenario it keeps what the engine pushed onto the waiting worker's reply key, every request that would have reached a broker, whether the intent was acknowledged, the engine's counters and the number of Redis round trips, and compares them with `test_runs/fixtures/order_engine.jsonl`.

The engine loop is run with a stop event already set, so it makes exactly one pass over the stream and returns rather than blocking. Nothing here waits.

No Redis, database, credentials or network are used, and no request leaves the process. The project's `.env` still has to exist, because importing the engine imports `utilities.configurations`.

Typical usage:

    python -m test_runs.order_engine
    python -m test_runs.order_engine --record
"""

import argparse
import copy
import json
import pathlib
import sys
import logging
import time

import requests

from test_runs import order_engine_routes
from test_runs import order_routes
from unified_broker_interface.utilities.order_engine import engine_lock
from unified_broker_interface.utilities.order_engine.engine_lock import EngineLock
from unified_broker_interface.utilities.order_engine.engine_placement import (
    EnginePlacement,
)
from unified_broker_interface.utilities.order_engine.engine_runner import OrderEngine
from unified_broker_interface.utilities.order_engine.intent_handoff import (
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.order_intent import OrderIntent
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent / 'fixtures' / 'order_engine.jsonl'
)
STALE_INTENT_SECONDS = 30.0
RESULT_TTL_SECONDS = 300


class FakeEngineStoreRedis(order_engine_routes.FakeEngineRedis):
    """The handoff's stand-in, widened with the consumer group, list and lock commands the engine uses.

    Attributes:
        groups (dict): Stream keys to the set of group names created on them.
        delivered (dict): Stream keys to every entry id ever handed out, which is what `>` reads past.
        pending (dict): Stream keys to the entry ids handed out but not yet acknowledged.
        expiries (dict): Keys to the expiry in seconds last set on them.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.groups = {}
        self.delivered = {}
        self.pending = {}
        self.expiries = {}

    def xgroup_create(self, key, group, id=None, mkstream=False):
        """Creates a consumer group, raising when it is already there, as Redis does.

        Args:
            key (str): The stream key.
            group (str): The group name.
            id (str | None): Accepted for compatibility with redis-py and ignored.
            mkstream (bool): Creates the stream when it does not exist.

        Returns:
            bool: True.

        Raises:
            Exception: With BUSYGROUP in its message when the group already exists.
        """
        del id
        if mkstream:
            self.streams.setdefault(key, [])
        created = self.groups.setdefault(key, set())
        if group in created:
            raise Exception('BUSYGROUP Consumer Group name already exists')
        created.add(group)
        return True

    def xreadgroup(self, group, consumer, streams, count=None, block=None):
        """Reads new or pending entries for one consumer group, never blocking.

        Args:
            group (str): The group name.
            consumer (str): The consumer name.
            streams (dict): Stream keys to `0` for pending entries or `>` for new ones.
            count (int | None): The most entries to read.
            block (int | None): Accepted for compatibility with redis-py and ignored, since the stand-in never waits.

        Returns:
            list: `(stream_key, entries)` pairs, with entries as `(entry_id, fields)`.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del group, consumer, block
        self.start_round_trip()
        response = []
        for key, position in streams.items():
            delivered = self.delivered.setdefault(key, [])
            pending = self.pending.setdefault(key, [])
            entries = []
            for entry_id, fields in self.streams.get(key, []):
                if position == '0':
                    if entry_id in pending:
                        entries.append((entry_id, fields))
                elif entry_id not in delivered:
                    delivered.append(entry_id)
                    pending.append(entry_id)
                    entries.append((entry_id, fields))
            if count is not None:
                entries = entries[:count]
            if entries:
                response.append((key, entries))
        return response

    def xack(self, key, group, entry_id):
        """Acknowledges one delivered entry.

        Args:
            key (str): The stream key.
            group (str): The group name.
            entry_id (str): The entry's id.

        Returns:
            int: 1 when the entry was delivered and is now acknowledged, and 0 otherwise.
        """
        del group
        self.start_round_trip()
        pending = self.pending.setdefault(key, [])
        if entry_id in pending:
            pending.remove(entry_id)
            return 1
        return 0

    def set(self, key, value, nx=False, ex=None):
        """Sets a string key, optionally only when it does not exist.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Only set the key when it does not already exist.
            ex (int | None): The expiry in seconds.

        Returns:
            bool | None: True when the key was set, and None when `nx` was given and it already existed.
        """
        self.start_round_trip()
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    def expire(self, key, seconds):
        """Records an expiry on a key.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            bool: True when the key exists.
        """
        self.start_round_trip()
        self.expiries[key] = seconds
        return key in self.strings or key in self.lists

    def delete(self, key):
        """Removes a key.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, and 0 otherwise.
        """
        self.start_round_trip()
        self.expiries.pop(key, None)
        if self.strings.pop(key, None) is not None:
            return 1
        return 0

    def run_rpush(self, key, value):
        """Appends to a list, without counting a round trip of its own.

        Args:
            key (str): The list key.
            value (str): The value.

        Returns:
            int: The list's new length.
        """
        entries = self.lists.setdefault(key, [])
        entries.append(value)
        return len(entries)

    def run_expire(self, key, seconds):
        """Records an expiry on a key, without counting a round trip of its own.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            bool: True.
        """
        self.expiries[key] = seconds
        return True

    def pipeline(self, transaction=True):
        """Starts a pipeline that also understands the list commands the engine queues.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            FakeEnginePipeline: The pipeline.
        """
        del transaction
        return FakeEnginePipeline(self)


class FakeEnginePipeline(order_routes.FakePipeline):
    """The order routes' pipeline, widened with the list commands the engine queues."""

    def rpush(self, key, value):
        """Queues an append to a list.

        Args:
            key (str): The list key.
            value (str): The value.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('rpush', (key, value)))
        return self

    def expire(self, key, seconds):
        """Queues an expiry on a key.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('expire', (key, seconds)))
        return self

    def execute(self):
        """Runs every queued command in one round trip.

        Returns:
            list: One reply per queued command, in order.

        Raises:
            redis.RedisError: When this round trip is set to fail.
            ValueError: When a queued command is not one the stand-in knows.
        """
        self.fake_redis.start_round_trip()
        replies = []
        for command_name, arguments in self.commands:
            if command_name == 'get':
                replies.append(self.fake_redis.run_get(*arguments))
            elif command_name == 'hget':
                replies.append(self.fake_redis.run_hget(*arguments))
            elif command_name == 'hmget':
                replies.append(self.fake_redis.run_hmget(*arguments))
            elif command_name == 'incr':
                replies.append(self.fake_redis.run_incr(*arguments))
            elif command_name == 'rpush':
                replies.append(self.fake_redis.run_rpush(*arguments))
            elif command_name == 'expire':
                replies.append(self.fake_redis.run_expire(*arguments))
            else:
                raise ValueError(
                    f'unsupported stand-in command: {command_name!r}'
                )
        self.commands = []
        return replies


class OnePassStop:
    """A stop event that lets the engine's loop run a fixed number of passes and then stop.

    The engine blocks on Redis for new entries and runs until it is asked to stop, neither of which suits a recording. This reports "not stopping" for the first few checks and "stopping" afterwards, so `run` makes exactly the passes a scenario needs and returns.

    Attributes:
        remaining (int): How many more checks report that the engine should keep going.
    """

    def __init__(self, passes):
        """Builds the stop event.

        Args:
            passes (int): How many passes of the loop to allow.

        Returns:
            None: This method returns nothing.
        """
        self.remaining = passes

    def is_set(self):
        """Whether the engine should stop, counting down one pass each time it is asked.

        Returns:
            bool: False while passes remain, and True afterwards.
        """
        if self.remaining > 0:
            self.remaining = self.remaining - 1
            return False
        return True

    def set(self):
        """Stops the engine at its next check.

        Returns:
            None: This method returns nothing.
        """
        self.remaining = 0

    def wait(self, seconds):
        """Returns at once instead of waiting, so a backoff costs no time.

        Args:
            seconds (float): Ignored.

        Returns:
            bool: True.
        """
        del seconds
        return True


class OrderEngineScenarios:
    """Every scenario the engine's recording covers.

    Attributes:
        bodies (OrderRoutesScenarios): The order routes' body builders, so the engine places the same orders the routes were recorded with.
        answers (OrderRoutesAnswers): The order routes' broker answers.
    """

    def __init__(self):
        """Builds the scenario set.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = order_routes.OrderRoutesScenarios()
        self.answers = order_routes.OrderRoutesAnswers()

    def intents(self, name, bodies, **settings):
        """Builds one scenario that puts intents on the stream and runs the engine.

        Args:
            name (str): The scenario name.
            bodies (list): One request body per intent.
            **settings: Any other scenario keys, such as `answer`, `deadline_ago` or `passes`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'kind': 'intents',
            'bodies': bodies,
        }
        scenario.update(settings)
        return scenario

    def build(self):
        """Builds every scenario, in the order the recording holds them.

        Returns:
            list: The scenarios.
        """
        order = self.bodies.market_order(dry_run=None)
        return [
            self.intents(
                'places_one_order_at_the_first_broker_that_takes_it',
                [
                    order,
                ],
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_broker_refusal_is_reported_as_rejected',
                [
                    order,
                ],
                answer=self.answers.json_answer(
                    400,
                    {
                        'stat': 'Not_Ok',
                        'emsg': 'Market is closed',
                    },
                ),
            ),
            self.intents(
                'a_lost_broker_answer_is_reported_as_unknown',
                [
                    order,
                ],
                answer=self.answers.raised_answer('ReadTimeout'),
            ),
            self.intents(
                'nothing_was_sent_is_reported_as_rejected',
                [
                    order,
                ],
                answer=self.answers.raised_answer('ConnectTimeout'),
            ),
            self.intents(
                'two_orders_take_turns_at_different_brokers',
                [
                    order,
                    order,
                ],
                answer=self.answers.json_answer(200, {}),
            ),
            self.intents(
                'an_unmapped_instrument_is_refused_without_a_broker_call',
                [
                    order,
                ],
                instrument_id='99999999-9999-5999-8999-999999999999',
            ),
            self.intents(
                'an_intent_past_its_deadline_is_not_placed',
                [
                    order,
                ],
                deadline_ago=120.0,
            ),
            self.intents(
                'an_intent_just_inside_its_grace_is_still_placed',
                [
                    order,
                ],
                deadline_ago=5.0,
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_entry_that_is_not_an_intent_is_acknowledged',
                [
                    order,
                ],
                corrupt=True,
            ),
            self.intents(
                'an_intent_naming_no_instrument_is_refused',
                [
                    order,
                ],
                instrument_id=None,
            ),
        ]


class OrderEngineSuite:
    """Runs every engine scenario, then records or compares the results.

    Attributes:
        fake_redis (FakeEngineStoreRedis): The stand-in the engine reads and writes.
        network (FakeBrokerNetwork): The stubbed broker network.
    """

    def __init__(self):
        """Builds the suite with an empty stand-in and a stubbed network.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = FakeEngineStoreRedis()
        self.network = order_routes.FakeBrokerNetwork()

    def build_state(self):
        """Builds a stand-in holding the order routes' starting contents.

        Returns:
            FakeEngineStoreRedis: The stand-in.
        """
        starting_state = order_routes.OrderRoutesState().build()
        fake_redis = FakeEngineStoreRedis()
        fake_redis.strings = starting_state.strings
        fake_redis.hashes = starting_state.hashes
        fake_redis.sorted_sets = starting_state.sorted_sets
        return fake_redis

    def write_intents(self, scenario):
        """Puts one intent on the stream per body the scenario names.

        Args:
            scenario (dict): The scenario.

        Returns:
            list: The reply keys the engine should answer on, in order.
        """
        reply_keys = []
        instrument_id = scenario.get(
            'instrument_id',
            order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
        )
        for position, body in enumerate(scenario['bodies']):
            intent = OrderIntent(body, instrument_id, 5.0)
            intent.intent_id = f'{position:032x}'
            intent.reply_key = (
                'unified:orders:intents:result:' + intent.intent_id
            )
            document = intent.document()
            deadline_ago = scenario.get('deadline_ago')
            if deadline_ago is not None:
                document['created_at'] = time.time() - deadline_ago - 5.0
                document['deadline_at'] = time.time() - deadline_ago
            entry = json.dumps(document)
            if scenario.get('corrupt'):
                entry = 'this is not an intent'
            self.fake_redis.streams.setdefault(INTENT_STREAM_KEY, []).append(
                (f'{position + 1}-0', {
                    INTENT_STREAM_FIELD: entry,
                }),
            )
            reply_keys.append(intent.reply_key)
        return reply_keys

    def shown_replies(self, reply_keys):
        """The answers the engine pushed, with the timings that differ between runs collapsed.

        Args:
            reply_keys (list): The reply keys in the order the intents were written.

        Returns:
            list: One answer per reply key, or None where the engine pushed nothing.
        """
        shown = []
        for reply_key in reply_keys:
            entries = self.fake_redis.lists.get(reply_key)
            if not entries:
                shown.append(None)
                continue
            reply = json.loads(entries[0])
            body = reply.get('body')
            if isinstance(body, dict):
                if isinstance(body.get('timing_ms'), dict):
                    body['timing_ms'] = sorted(body['timing_ms'])
                if isinstance(body.get('expired_seconds'), (int, float)):
                    body['expired_seconds'] = round(body['expired_seconds'])
            shown.append(reply)
        return shown

    def run_scenario(self, scenario):
        """Runs one scenario against a fresh stand-in and a fresh engine.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = self.build_state()
        self.network.reset(scenario.get('answer'))
        reply_keys = self.write_intents(scenario)

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        lock = EngineLock(self.fake_redis, logger)
        engine = OrderEngine(
            self.fake_redis,
            placement,
            lock,
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
        )
        self.fake_redis.round_trips = 0
        exit_code = engine.run(OnePassStop(scenario.get('passes', 3)))

        delivered = self.fake_redis.pending.get(INTENT_STREAM_KEY, [])
        return {
            'name': scenario['name'],
            'exit_code': exit_code,
            'replies': self.shown_replies(reply_keys),
            'sent': copy.deepcopy(self.network.sent_requests),
            'unacknowledged': list(delivered),
            'placed': engine.placed,
            'refused': engine.refused,
            'expired': engine.expired,
            'redis_round_trips': self.fake_redis.round_trips,
            'reply_ttl_seconds': [
                self.fake_redis.expiries.get(reply_key)
                for reply_key in reply_keys
            ],
        }

    def run_lock_checks(self):
        """Checks the single-engine lock directly, since losing it depends on a clock the loop owns.

        Returns:
            list: One recorded result per check.
        """
        results = []

        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        first = EngineLock(self.fake_redis, logger)
        first.holder = '111'
        second = EngineLock(self.fake_redis, logger)
        second.holder = '222'
        results.append({
            'name': 'the_first_engine_takes_the_lock',
            'taken': bool(first.take()),
            'holder': self.fake_redis.strings.get(engine_lock.LOCK_KEY),
            'expiry_seconds': self.fake_redis.expiries.get(
                engine_lock.LOCK_KEY,
            ),
        })
        results.append({
            'name': 'a_second_engine_cannot_take_the_lock',
            'taken': bool(second.take()),
            'holder': self.fake_redis.strings.get(engine_lock.LOCK_KEY),
        })
        results.append({
            'name': 'the_holder_can_refresh_the_lock',
            'held': bool(first.refresh()),
        })
        self.fake_redis.strings[engine_lock.LOCK_KEY] = '333'
        results.append({
            'name': 'an_engine_that_lost_the_lock_stops',
            'held': bool(first.refresh()),
        })
        first.holder = '333'
        first.release()
        results.append({
            'name': 'releasing_the_lock_removes_it',
            'holder': self.fake_redis.strings.get(engine_lock.LOCK_KEY),
        })
        return results

    def run_every_scenario(self):
        """Runs every scenario with the broker network replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_request = requests.Session.request
        original_excluded = api_configuration['order_excluded_brokers']
        original_selector = api_configuration['order_broker_selector']
        requests.Session.request = self.network.request
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_broker_selector'] = 'round_robin'
        try:
            results = []
            for scenario in OrderEngineScenarios().build():
                results.append(self.run_scenario(scenario))
            results.extend(self.run_lock_checks())
        finally:
            requests.Session.request = original_request
            api_configuration['order_excluded_brokers'] = original_excluded
            api_configuration['order_broker_selector'] = original_selector
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
            description='Check the order engine against its recorded behaviour.',
        )
        parser.add_argument(
            '--record',
            action='store_true',
            help='rewrite the recording from the current code',
        )
        arguments = parser.parse_args()
        logging.getLogger('test_runs.order_engine').setLevel(logging.CRITICAL)
        results = self.run_every_scenario()
        if arguments.record:
            return self.record(results)
        return self.compare(results)


if __name__ == '__main__':
    sys.exit(OrderEngineSuite().run())
