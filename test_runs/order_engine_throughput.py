"""Offline load test of the order engine's broker lanes, against ten stub brokers that each take 200 milliseconds to answer.

It writes a burst of plain orders to a stand-in intent stream, runs the engine with its worker lanes until every order is answered, and reports how many orders a second went to each broker and in total. It runs twice, once with one worker per broker and once with ten, and requires that every order was accepted, that the rate budget never gave one broker room for more than 10 messages in any one-second span, and that ten workers reach at least 80 orders a second across the ten brokers. It also reports the most requests a stub broker received within one second, which can exceed 10 by one when thread scheduling delays one request more than another between taking room and sending.

Nothing leaves the machine, and no Redis, database or credentials are used.

Typical usage:

    python -m test_runs.order_engine_throughput
"""

import argparse
import json
import logging
import sys
import threading
import time
import urllib.parse

import requests

from test_runs import order_engine
from test_runs import order_routes
from test_runs import redis_stand_ins
from unified_broker_interface.utilities.broker_orders.utilities.registry import (
    BROKER_ORDER_CLASSES,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    EngineLock,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_runner import (
    OrderEngine,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.loss_lockout import (
    LossLockout,
)
from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)
from unified_broker_interface.utilities.order_engine.utilities.order_to_trade_ratio import (
    OrderToTradeRatio,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RATE_KEY_PREFIX,
    RateBudget,
)
from unified_broker_interface.utilities.order_engine.utilities.risk_gates import (
    RiskGates,
)
from utilities.configurations import api_configuration

BROKER_LATENCY_SECONDS = 0.2
ORDERS_PER_BROKER = 30
PER_BROKER_LIMIT = 10
MINIMUM_TOTAL_RATE = 80.0
KOTAK_HOST = 'kotaksecurities.com'


class SlowBrokerNetwork:
    """Ten stub brokers that accept every order after a fixed delay, recording when each request was sent.

    Attributes:
        latency_seconds (float): How long every broker takes to answer.
        answers (order_routes.OrderRoutesAnswers): The recorded success bodies, one per broker.
        hosts (dict): Each broker's API host, or a part of it, to the broker's name.
        sends_lock (threading.Lock): Guards `sends`, which many worker threads append to.
        sends (list): One `(broker_name, monotonic_time)` pair per request, taken when it was sent.
    """

    def __init__(self, latency_seconds):
        """Builds the network.

        Args:
            latency_seconds (float): How long every broker takes to answer.

        Returns:
            None: This method returns nothing.
        """
        self.latency_seconds = latency_seconds
        self.answers = order_routes.OrderRoutesAnswers()
        self.hosts = {}
        for broker_order_class in BROKER_ORDER_CLASSES:
            if broker_order_class.WARM_URL:
                host = urllib.parse.urlsplit(broker_order_class.WARM_URL).hostname
                self.hosts[host] = broker_order_class.BROKER_NAME
        self.hosts[KOTAK_HOST] = 'kotak'
        self.sends_lock = threading.Lock()
        self.sends = []

    def broker_for(self, url):
        """The broker a request is addressed to.

        Args:
            url (str): The request's URL.

        Returns:
            str: The broker's name.

        Raises:
            ValueError: When the URL names no known broker host.
        """
        for host, broker_name in self.hosts.items():
            if host in url:
                return broker_name
        raise ValueError(f'no stub broker answers {url}')

    def request(self, method, url, **keyword_arguments):
        """Answers one request with the broker's success body after the delay, noting when it was sent.

        It replaces `requests.Session.request` as a bound method of this network, so it is not given the session.

        Args:
            method (str): The HTTP method, unused.
            url (str): The URL.
            **keyword_arguments: The remaining `requests` arguments, unused.

        Returns:
            order_routes.FakeResponse: The broker's success answer.
        """
        del method, keyword_arguments
        broker_name = self.broker_for(url)
        with self.sends_lock:
            self.sends.append((broker_name, time.monotonic()))
        time.sleep(self.latency_seconds)
        return order_routes.FakeResponse(
            200,
            json_body=self.answers.place_success(broker_name),
        )

    def most_in_one_second(self):
        """The most requests any one broker received within any one-second span.

        Returns:
            dict: Each broker's name to its largest count.
        """
        with self.sends_lock:
            sends = list(self.sends)
        return MomentCounter().most_in_one_second(sends)


class MomentCounter:
    """Counts how many moments of each broker fall within the busiest one-second span."""

    def most_in_one_second(self, pairs):
        """The most moments any one broker has within any one-second span.

        Args:
            pairs (list): One `(broker_name, monotonic_time)` pair per moment.

        Returns:
            dict: Each broker's name to its largest count.
        """
        sends = pairs
        moments_by_broker = {}
        for broker_name, moment in sends:
            moments_by_broker.setdefault(broker_name, []).append(moment)
        most = {}
        for broker_name, moments in moments_by_broker.items():
            moments.sort()
            largest = 0
            start = 0
            for end in range(len(moments)):
                while moments[end] - moments[start] >= 1.0:
                    start = start + 1
                largest = max(largest, end - start + 1)
            most[broker_name] = largest
        return most


class WaitingEngineRedis(redis_stand_ins.FakeEngineStoreRedis):
    """The engine suite's Redis stand-in, pausing briefly on an empty stream read the way a blocking read would, so the main thread does not spin."""

    def xreadgroup(self, group, consumer, streams, count=None, block=None):
        """Reads entries, pausing ten milliseconds when a blocking read finds none.

        Args:
            group (str): The group name.
            consumer (str): The consumer name.
            streams (dict): Stream keys to positions.
            count (int | None): The most entries to read.
            block (int | None): The blocking time, which here only decides whether to pause.

        Returns:
            list: `(stream_key, entries)` pairs.
        """
        response = super().xreadgroup(group, consumer, streams, count, block)
        if not response and block:
            time.sleep(0.01)
        return response


class StopWhenAnswered:
    """Stops the engine once every intent has an answer, or after a time limit.

    Attributes:
        fake_redis (WaitingEngineRedis): The stand-in holding the answers.
        reply_keys (list): The reply key of every intent.
        limit_seconds (float): The longest to wait.
        started_at (float): When waiting began, on the monotonic clock.
        stop_event (threading.Event): The event the engine watches.
        answered_at (float | None): When the last answer arrived, on the monotonic clock.
    """

    def __init__(self, fake_redis, reply_keys, limit_seconds):
        """Builds the stopper.

        Args:
            fake_redis (WaitingEngineRedis): The stand-in holding the answers.
            reply_keys (list): The reply key of every intent.
            limit_seconds (float): The longest to wait.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = fake_redis
        self.reply_keys = reply_keys
        self.limit_seconds = limit_seconds
        self.started_at = time.monotonic()
        self.stop_event = threading.Event()
        self.answered_at = None

    def answered_count(self):
        """How many intents have an answer.

        Returns:
            int: The count.
        """
        count = 0
        for reply_key in self.reply_keys:
            if self.fake_redis.lists.get(reply_key):
                count = count + 1
        return count

    def watch(self):
        """Sets the stop event when every intent is answered or the limit passes.

        Returns:
            None: This method returns nothing.
        """
        while time.monotonic() - self.started_at < self.limit_seconds:
            if self.answered_count() == len(self.reply_keys):
                self.answered_at = time.monotonic()
                break
            time.sleep(0.005)
        self.stop_event.set()

    def is_set(self):
        """Whether the engine should stop.

        Returns:
            bool: True once every intent is answered or the limit passed.
        """
        return self.stop_event.is_set()

    def wait(self, seconds):
        """Waits for the stop event, as `threading.Event.wait` does.

        Args:
            seconds (float): The longest to wait.

        Returns:
            bool: True when the event is set.
        """
        return self.stop_event.wait(seconds)


class OrderEngineThroughputSuite:
    """Runs the load test with one worker per broker and with ten, and checks the results.

    Attributes:
        logger (logging.Logger): The logger, kept quiet.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('test_runs.order_engine_throughput')
        self.logger.setLevel(logging.CRITICAL)
        self.passed = 0
        self.failed = []

    def check(self, name, condition, detail):
        """Records and prints one check.

        Args:
            name (str): The check's name.
            condition (bool): Whether it passed.
            detail (str): What was observed.

        Returns:
            None: This method returns nothing.
        """
        if condition:
            self.passed = self.passed + 1
            print(f'ok      {name}: {detail}')
        else:
            self.failed.append(name)
            print(f'FAILED  {name}: {detail}')

    def build_state(self):
        """Builds the stand-in with the order routes' logins, settings and instruments.

        Returns:
            WaitingEngineRedis: The stand-in.
        """
        starting_state = order_routes.OrderRoutesState().build()
        fake_redis = WaitingEngineRedis()
        fake_redis.strings = starting_state.strings
        fake_redis.hashes = starting_state.hashes
        fake_redis.sorted_sets = starting_state.sorted_sets
        return fake_redis

    def write_intents(self, fake_redis, count):
        """Writes one plain MARKET order intent per count to the stand-in's intent stream.

        Args:
            fake_redis (WaitingEngineRedis): The stand-in.
            count (int): How many intents to write.

        Returns:
            list: Each intent's reply key.
        """
        body = order_routes.OrderRoutesScenarios().market_order(dry_run=None)
        reply_keys = []
        for position in range(count):
            intent = OrderIntent(
                dict(body),
                order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                60.0,
            )
            fake_redis.streams.setdefault(INTENT_STREAM_KEY, []).append(
                (f'{position + 1}-0', {
                    INTENT_STREAM_FIELD: json.dumps(intent.document()),
                }),
            )
            reply_keys.append(intent.reply_key)
        return reply_keys

    def run_once(self, workers_per_broker):
        """Runs the engine over a burst of orders with a number of workers per broker.

        Args:
            workers_per_broker (int): How many workers each broker's lane has.

        Returns:
            dict: `answered`, `accepted`, `seconds`, `per_broker` (orders a second by broker), `total_rate` and `most_in_one_second`.
        """
        fake_redis = self.build_state()
        network = SlowBrokerNetwork(BROKER_LATENCY_SECONDS)
        original_request = requests.Session.request
        requests.Session.request = network.request
        try:
            placement = EnginePlacement(fake_redis, self.logger)
            broker_names = placement.order_placement.broker_names
            order_count = ORDERS_PER_BROKER * len(broker_names)
            reply_keys = self.write_intents(fake_redis, order_count)
            gates = RiskGates(
                RateBudget(fake_redis, 0, PER_BROKER_LIMIT, 5.0, self.logger),
                LossLockout(fake_redis, 0, self.logger),
                OrderToTradeRatio(),
            )
            starting_workers = {}
            for broker_name in broker_names:
                starting_workers[broker_name] = workers_per_broker
            router = ParentRouter(
                broker_names,
                starting_workers,
                workers_per_broker,
                self.logger,
            )
            router.start()
            engine = OrderEngine(
                fake_redis,
                placement,
                EngineLock(fake_redis, self.logger),
                self.logger,
                30.0,
                300,
                order_engine.RecordingEventLog(),
                ParentStore(fake_redis),
                None,
                gates,
                router=router,
                entries_per_read=100,
            )
            stopper = StopWhenAnswered(fake_redis, reply_keys, 120.0)
            watcher = threading.Thread(target=stopper.watch, daemon=True)
            watcher.start()
            engine.run(stopper)
            watcher.join()
        finally:
            requests.Session.request = original_request
        seconds = (stopper.answered_at or time.monotonic()) - stopper.started_at
        accepted = 0
        for reply_key in reply_keys:
            stored = fake_redis.lists.get(reply_key) or []
            if not stored:
                continue
            answer = json.loads(stored[0])
            if answer.get('body', {}).get('outcome') == 'accepted':
                accepted = accepted + 1
        sent_by_broker = {}
        for broker_name, _ in network.sends:
            sent_by_broker[broker_name] = sent_by_broker.get(broker_name, 0) + 1
        per_broker = {}
        for broker_name in sorted(sent_by_broker):
            per_broker[broker_name] = round(sent_by_broker[broker_name] / seconds, 1)
        return {
            'answered': stopper.answered_count(),
            'orders': order_count,
            'accepted': accepted,
            'seconds': round(seconds, 2),
            'per_broker': per_broker,
            'total_rate': round(order_count / seconds, 1),
            'most_given_room_in_one_second': MomentCounter().most_in_one_second(
                self.admissions(fake_redis),
            ),
            'most_received_in_one_second': network.most_in_one_second(),
        }

    def admissions(self, fake_redis):
        """Every message the rate budget gave room to, at the moment its window counted it.

        Args:
            fake_redis (WaitingEngineRedis): The stand-in whose rate window script logged each message.

        Returns:
            list: One `(broker_name, seconds)` pair per message.
        """
        pairs = []
        for key, microseconds in fake_redis.rate_log:
            broker_name = key[len(RATE_KEY_PREFIX):]
            pairs.append((broker_name, microseconds / 1000000))
        return pairs

    def run(self):
        """Runs the load test from the command line.

        Returns:
            int: The exit code: 0 when every check passed, 1 otherwise.
        """
        parser = argparse.ArgumentParser(
            description='Measure the order engine across ten slow stub brokers.',
        )
        parser.parse_args()
        logging.disable(logging.CRITICAL)
        api_configuration['order_warm_brokers'] = [
            '',
        ]
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_broker_selector'] = 'round_robin'
        one_worker = self.run_once(1)
        ten_workers = self.run_once(10)
        for label, result in (('1 worker per broker', one_worker), ('10 workers per broker', ten_workers)):
            print(
                f'{label}: {result["answered"]} of {result["orders"]} answered, '
                f'{result["accepted"]} accepted, in {result["seconds"]} s, '
                f'{result["total_rate"]} orders a second in total on average, '
                'counting each broker\'s full first second'
            )
            print(f'  orders a second by broker: {result["per_broker"]}')
            print(f'  most given room at one broker in any one second: {result["most_given_room_in_one_second"]}')
            print(f'  most received by one stub broker in any one second: {result["most_received_in_one_second"]}')
        for label, result in (('one worker', one_worker), ('ten workers', ten_workers)):
            self.check(
                f'every order is accepted with {label} per broker',
                result['accepted'] == result['orders'],
                f'{result["accepted"]} of {result["orders"]}',
            )
            most = max(result['most_given_room_in_one_second'].values() or [0])
            received = max(result['most_received_in_one_second'].values() or [0])
            self.check(
                f'the budget never gives one broker room for more than {PER_BROKER_LIMIT} messages in any second with {label}',
                most <= PER_BROKER_LIMIT,
                f'most given room in one second {most}, most received by a stub broker in one second {received}',
            )
        self.check(
            f'ten workers per broker reach {MINIMUM_TOTAL_RATE:.0f} orders a second across ten brokers',
            ten_workers['total_rate'] >= MINIMUM_TOTAL_RATE,
            f'{ten_workers["total_rate"]} orders a second',
        )
        self.check(
            'ten workers per broker are faster than one',
            ten_workers['total_rate'] > one_worker['total_rate'],
            f'{ten_workers["total_rate"]} against {one_worker["total_rate"]} orders a second',
        )
        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(OrderEngineThroughputSuite().run())
