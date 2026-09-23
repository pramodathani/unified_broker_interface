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
import uuid

import requests

from test_runs import order_engine_routes
from test_runs import order_routes
from unified_broker_interface.utilities.order_engine.utilities import engine_lock
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import EngineLock
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_runner import OrderEngine
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.order_intent import OrderIntent
from unified_broker_interface.utilities.order_engine.utilities.parent_order import ParentOrder
from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
)
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    OrderUpdateFollower,
)
from unified_broker_interface.utilities.order_engine.utilities.loss_lockout import (
    LossLockout,
)
from unified_broker_interface.utilities.order_engine.utilities.order_to_trade_ratio import (
    OrderToTradeRatio,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import ParentStore
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)
from unified_broker_interface.utilities.order_engine.utilities.risk_gates import (
    RiskGates,
)
from unified_broker_interface.utilities.order_engine.utilities import (
    synthetic_order_event_log,
)
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
        self.sets = {}

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
        if not mkstream and key not in self.streams:
            raise Exception(
                'ERR The XGROUP subcommand requires the key to exist',
            )
        del id
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

    def smembers(self, key):
        """Every member of a set.

        Args:
            key (str): The set key.

        Returns:
            set: The members.
        """
        self.start_round_trip()
        return set(self.sets.get(key, set()))

    def run_hgetall(self, key):
        """Every field in a hash, without counting a round trip of its own.

        Args:
            key (str): The hash key.

        Returns:
            dict: The fields and values, or an empty dictionary.
        """
        return dict(self.hashes.get(key, {}))

    def run_hset(self, key, field, value):
        """Sets a hash field, without counting a round trip of its own.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            int: 1 when the field is new, and 0 when it was replaced.
        """
        fields = self.hashes.setdefault(key, {})
        new_field = field not in fields
        fields[field] = value
        return 1 if new_field else 0

    def run_sadd(self, key, member):
        """Adds a set member, without counting a round trip of its own.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            int: 1 when the member is new, and 0 when it was already there.
        """
        members = self.sets.setdefault(key, set())
        new_member = member not in members
        members.add(member)
        return 1 if new_member else 0

    def run_srem(self, key, member):
        """Removes a set member, without counting a round trip of its own.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            int: 1 when the member was there, and 0 otherwise.
        """
        members = self.sets.setdefault(key, set())
        if member in members:
            members.discard(member)
            return 1
        return 0

    def run_expireat(self, key, moment):
        """Records an absolute expiry on a key, without counting a round trip of its own.

        Args:
            key (str): The key.
            moment (int): The epoch the key expires at.

        Returns:
            bool: True.
        """
        self.expiries[key] = moment
        return True

    def run_delete(self, key):
        """Removes a key of any type, without counting a round trip of its own.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, and 0 otherwise.
        """
        self.expiries.pop(key, None)
        existed = (
            self.strings.pop(key, None) is not None
            or self.hashes.pop(key, None) is not None
            or self.sets.pop(key, None) is not None
            or self.lists.pop(key, None) is not None
        )
        return 1 if existed else 0

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

    def hset(self, key, field, value):
        """Queues a hash write.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('hset', (key, field, value)))
        return self

    def sadd(self, key, member):
        """Queues a set addition.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('sadd', (key, member)))
        return self

    def srem(self, key, member):
        """Queues a set removal.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('srem', (key, member)))
        return self

    def expireat(self, key, moment):
        """Queues an absolute expiry.

        Args:
            key (str): The key.
            moment (int): The epoch the key expires at.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('expireat', (key, moment)))
        return self

    def delete(self, key):
        """Queues a key removal.

        Args:
            key (str): The key.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('delete', (key,)))
        return self

    def hgetall(self, key):
        """Queues a read of every field in a hash.

        Args:
            key (str): The hash key.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('hgetall', (key,)))
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
            elif command_name == 'hset':
                replies.append(self.fake_redis.run_hset(*arguments))
            elif command_name == 'sadd':
                replies.append(self.fake_redis.run_sadd(*arguments))
            elif command_name == 'srem':
                replies.append(self.fake_redis.run_srem(*arguments))
            elif command_name == 'expireat':
                replies.append(self.fake_redis.run_expireat(*arguments))
            elif command_name == 'delete':
                replies.append(self.fake_redis.run_delete(*arguments))
            elif command_name == 'hgetall':
                replies.append(self.fake_redis.run_hgetall(*arguments))
            else:
                raise ValueError(
                    f'unsupported stand-in command: {command_name!r}'
                )
        self.commands = []
        return replies


class RecordingEventLog:
    """Stands in for the event log, keeping every transition in a list instead of a database.

    The engine's recovery reads this back, so the stand-in has to behave like the table in the one way that matters: `read_since` returns rows oldest first within each parent.

    Attributes:
        events (list): Every event recorded, in the order it was written.
        failing_event (int | None): The 1-based write that raises, or None when none does.
        writes (int): How many events have been written.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []
        self.failing_event = None
        self.writes = 0

    def apply_table(self):
        """Does nothing, since there is no table.

        Returns:
            None: This method returns nothing.
        """

    def record(self, event):
        """Keeps one transition.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When this write is the one set to fail.
        """
        self.writes = self.writes + 1
        if self.writes == self.failing_event:
            raise RuntimeError('stand-in event log failure')
        self.events.append(dict(event))

    def record_many(self, events):
        """Keeps several transitions.

        Args:
            events (list): The events.

        Returns:
            None: This method returns nothing.
        """
        for event in events:
            self.record(event)

    def read_since(self, moment):
        """Every transition kept, ordered as the table orders them.

        Args:
            moment (datetime.datetime): Ignored, since the stand-in keeps only one run's events.

        Returns:
            list: The events, by parent and then sequence.
        """
        del moment
        return sorted(
            self.events,
            key=lambda event: (
                str(event.get('parent_order_id')),
                event.get('sequence') or 0,
            ),
        )

    def shown(self):
        """The events with the values that differ between runs left out.

        Returns:
            list: One dictionary per event, carrying only what a recording can compare.
        """
        shown = []
        for event in self.events:
            kept = {}
            for name, value in event.items():
                if name in ('time', 'engine_instance', 'parent_order_id', 'intent_id'):
                    continue
                if name == 'leg_id' and value:
                    kept[name] = 'leg:' + str(value).rsplit(':', 1)[1]
                    continue
                kept[name] = value
            shown.append(kept)
        return shown


class CountingUuid:
    """A stand-in for `uuid.uuid4` that counts rather than being random.

    Two things in one scenario need different identifiers — two parents, and the tag Groww generates for itself — so replacing `uuid.uuid4` with one constant the way the route suites do is not open here. Counting gives values that are distinct within a scenario and the same on every run, and the count is reset before each scenario so one scenario's numbering does not depend on what ran before it.

    Attributes:
        count (int): How many identifiers have been handed out since the last reset.
    """

    def __init__(self):
        """Builds the counter.

        Returns:
            None: This method returns nothing.
        """
        self.count = 0

    def reset(self):
        """Starts the numbering again, before a scenario.

        Returns:
            None: This method returns nothing.
        """
        self.count = 0

    def __call__(self):
        """The next identifier.

        Returns:
            uuid.UUID: A version 4 identifier whose value is the count.
        """
        self.count = self.count + 1
        return uuid.UUID(int=self.count, version=4)


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

    def quote(self, **overrides):
        """A live quote with five levels each side, as `unified:quotes:live` holds one.

        Args:
            **overrides: Fields to replace on the quote.

        Returns:
            dict: The quote.
        """
        document = {
            'last_price': 1000.10,
            'average_price': 999.80,
            'previous_close': 995.00,
            'depth': {
                'buy': [
                    {
                        'price': 1000.00 - index * 0.05,
                        'quantity': 100,
                        'orders': 1,
                    }
                    for index in range(5)
                ],
                'sell': [
                    {
                        'price': 1000.05 + index * 0.05,
                        'quantity': 100,
                        'orders': 1,
                    }
                    for index in range(5)
                ],
            },
        }
        document.update(overrides)
        return document

    def positions(self, quantity, product='intraday'):
        """A unified positions document holding one net position in RELIANCE.

        Args:
            quantity (float): The net quantity, signed.
            product (str): The product, on the vocabulary the REST API answers with.

        Returns:
            dict: The document.
        """
        return {
            'net': [
                {
                    'instrument_id': (
                        order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[
                            'reliance'
                        ]
                    ),
                    'product': product,
                    'quantity': quantity,
                },
            ],
            'day': [],
        }

    def referenced(self, price_reference=None, quantity_reference=None, **overrides):
        """A LIMIT order that names a reference instead of a price or a quantity.

        Args:
            price_reference (dict | None): The price reference.
            quantity_reference (dict | None): The quantity reference.
            **overrides: Other body fields to replace.

        Returns:
            dict: The request body.
        """
        overrides.setdefault('order_type', 'LIMIT')
        body = self.bodies.market_order(
            dry_run=None,
            **overrides,
        )
        if price_reference is not None:
            body['price_reference'] = price_reference
        if quantity_reference is not None:
            body['quantity_reference'] = quantity_reference
        return body

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
                'the_event_log_fails_before_the_order_is_sent',
                [
                    order,
                ],
                failing_event=2,
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'the_event_log_fails_after_the_order_is_sent',
                [
                    order,
                ],
                failing_event=3,
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'the_rate_budget_refuses_a_burst_it_cannot_absorb',
                [
                    order,
                    order,
                    order,
                ],
                gated=True,
                rate_per_second=2,
                rate_per_broker_per_second=2,
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_losing_day_past_its_limit_places_nothing',
                [
                    order,
                ],
                gated=True,
                loss_limit=5000,
                funds={
                    'pnl': {
                        'realized': -4000.0,
                        'unrealized': -2500.0,
                    },
                },
            ),
            self.intents(
                'a_losing_day_inside_its_limit_still_trades',
                [
                    order,
                ],
                gated=True,
                loss_limit=5000,
                funds={
                    'pnl': {
                        'realized': -1000.0,
                        'unrealized': -500.0,
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'no_loss_limit_means_no_lockout',
                [
                    order,
                ],
                gated=True,
                funds={
                    'pnl': {
                        'realized': -900000.0,
                        'unrealized': 0.0,
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'funds_that_cannot_be_read_do_not_lock_trading_out',
                [
                    order,
                ],
                gated=True,
                loss_limit=5000,
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
            self.intents(
                'an_offer_level_reference_becomes_a_price',
                [
                    self.referenced({
                        'kind': 'offer_level',
                        'level': 2,
                    }),
                ],
                quote=self.quote(),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_mid_reference_rounds_to_the_passive_side',
                [
                    self.referenced({
                        'kind': 'mid',
                    }),
                ],
                quote=self.quote(),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_marketable_reference_crosses_with_a_buffer',
                [
                    self.referenced({
                        'kind': 'marketable',
                        'buffer_percent': 0.1,
                    }),
                ],
                quote=self.quote(),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_vwap_reference_uses_the_average_price',
                [
                    self.referenced({
                        'kind': 'vwap',
                    }),
                ],
                quote=self.quote(),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_level_deeper_than_the_book_is_refused',
                [
                    self.referenced({
                        'kind': 'bid_level',
                        'level': 5,
                    }),
                ],
                quote=self.quote(depth={
                    'buy': [
                        {
                            'price': 1000.00,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': 1000.05,
                            'quantity': 100,
                        },
                    ],
                }),
            ),
            self.intents(
                'a_reference_without_a_quote_is_refused',
                [
                    self.referenced({
                        'kind': 'mid',
                    }),
                ],
            ),
            self.intents(
                'liquidating_a_long_sells_all_of_it',
                [
                    self.referenced(
                        quantity_reference={
                            'kind': 'liquidate_position',
                        },
                        order_type='MARKET',
                        quantity=None,
                    ),
                ],
                positions=self.positions(75),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'liquidating_a_short_buys_it_back',
                [
                    self.referenced(
                        quantity_reference={
                            'kind': 'liquidate_position',
                        },
                        order_type='MARKET',
                        quantity=None,
                    ),
                ],
                positions=self.positions(-40),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'reducing_a_position_cannot_close_more_than_is_held',
                [
                    self.referenced(
                        quantity_reference={
                            'kind': 'reduce_position',
                        },
                        order_type='MARKET',
                        quantity=500,
                    ),
                ],
                positions=self.positions(75),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_order_below_the_freeze_limit_is_sent_whole',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=10,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '100',
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_order_above_the_freeze_limit_is_split_evenly',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=250,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '100',
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'every_slice_goes_to_the_same_broker',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=300,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '100',
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_broker_publishing_no_freeze_limit_sends_it_whole',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=250,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                attributes={
                    'zerodha': {
                        'freeze_quantity': '100',
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_order_needing_too_many_slices_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=5000,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '10',
                    },
                },
            ),
            self.intents(
                'a_ladder_spreads_its_rungs_across_the_range',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=100,
                        synthetic={
                            'type': 'ladder',
                            'from_price': 995,
                            'to_price': 1000,
                            'steps': 3,
                        },
                    ),
                ],
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_ladder_needs_a_quantity_for_every_rung',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=2,
                        synthetic={
                            'type': 'ladder',
                            'from_price': 995,
                            'to_price': 1000,
                            'steps': 5,
                        },
                    ),
                ],
            ),
            self.intents(
                'a_ladder_with_one_step_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=10,
                        synthetic={
                            'type': 'ladder',
                            'from_price': 995,
                            'to_price': 1000,
                            'steps': 1,
                        },
                    ),
                ],
            ),
            self.intents(
                'an_unknown_synthetic_type_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        synthetic={
                            'type': 'iron_condor',
                        },
                    ),
                ],
            ),
            self.intents(
                'closing_a_position_that_is_not_held_is_refused',
                [
                    self.referenced(
                        quantity_reference={
                            'kind': 'liquidate_position',
                        },
                        order_type='MARKET',
                        quantity=None,
                    ),
                ],
                positions=self.positions(0),
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
        self.counting_uuid = CountingUuid()

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
                if body.get('parent_id') is not None:
                    body['parent_id'] = self.shown_parent_id(body['parent_id'])
            shown.append(reply)
        return shown

    def shown_parent_id(self, parent_id):
        """A parent's id as the recording holds it, which is its shape rather than its value.

        A parent gets a fresh `uuid4` every run, and two parents in one scenario must have different ones, so patching `uuid.uuid4` the way the route suites do is not open here. What is worth pinning is that the answer carries a parent id at all and that it is a real identifier.

        Args:
            parent_id (str): The parent's id.

        Returns:
            str: `<uuid4>` when it parses as one, and the value itself when it does not.
        """
        try:
            parsed = uuid.UUID(str(parent_id))
        except ValueError:
            return str(parent_id)
        return f'<uuid{parsed.version}>'

    def build_gates(self, scenario, logger):
        """The risk gates for one scenario, or None when it names none.

        Args:
            scenario (dict): The scenario.
            logger (logging.Logger): The logger.

        Returns:
            RiskGates | None: The gates.
        """
        if not scenario.get('gated'):
            return None
        funds = scenario.get('funds')
        if funds is not None:
            self.fake_redis.strings['unified:portfolio:funds'] = json.dumps(
                funds,
            )
        return RiskGates(
            RateBudget(
                scenario.get('rate_per_second', 8),
                scenario.get('rate_per_broker_per_second', 5),
                scenario.get('rate_wait_seconds', 0),
                logger,
            ),
            LossLockout(
                self.fake_redis,
                scenario.get('loss_limit', 0),
                logger,
            ),
            OrderToTradeRatio(),
        )

    def run_scenario(self, scenario):
        """Runs one scenario against a fresh stand-in and a fresh engine.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = self.build_state()
        if scenario.get('quote') is not None:
            self.fake_redis.hashes['unified:quotes:live'] = {
                order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[
                    'reliance'
                ]: json.dumps(scenario['quote']),
            }
        if scenario.get('attributes') is not None:
            self.fake_redis.hashes[
                f'unified:catalogue:{order_routes.MAPPING_DATE}:'
                'additional_attributes'
            ] = {
                order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[
                    'reliance'
                ]: json.dumps(scenario['attributes']),
            }
        if scenario.get('positions') is not None:
            self.fake_redis.strings['unified:portfolio:positions'] = json.dumps(
                scenario['positions'],
            )
        self.network.reset(scenario.get('answer'))
        self.counting_uuid.reset()
        reply_keys = self.write_intents(scenario)

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        lock = EngineLock(self.fake_redis, logger)
        event_log = RecordingEventLog()
        event_log.failing_event = scenario.get('failing_event')
        gates = self.build_gates(scenario, logger)
        engine = OrderEngine(
            self.fake_redis,
            placement,
            lock,
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            ParentStore(self.fake_redis),
            None,
            gates,
        )
        self.fake_redis.round_trips = 0
        exit_code = engine.run(OnePassStop(scenario.get('passes', 3)))

        delivered = self.fake_redis.pending.get(INTENT_STREAM_KEY, [])
        return {
            'name': scenario['name'],
            'exit_code': exit_code,
            'replies': self.shown_replies(reply_keys),
            'sent': copy.deepcopy(self.network.sent_requests),
            'events': event_log.shown(),
            'open_parents': len(self.fake_redis.sets.get('unified:orders:parents:open', set())),
            'stored_parents': len(self.fake_redis.hashes.get('unified:orders:parents', {})),
            'children': sorted(self.fake_redis.hashes.get('unified:orders:children', {})),
            'gates': gates.counts() if gates is not None else None,
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

    def parent_events(self):
        """The transitions a plain order records, from received to completed.

        Returns:
            list: The events, oldest first.
        """
        parent_order_id = '11111111-2222-4333-8444-555555555555'
        leg_id = f'{parent_order_id}:1'
        return [
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'intent_id': '66666666-7777-4888-8999-000000000000',
                'instrument_id': '11111111-1111-5111-8111-000000000001',
                'detail': {
                    'body': {
                        'quantity': 10,
                        'tag': 'callerTag',
                    },
                },
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 2,
                'event': 'leg_requested',
                'leg_id': leg_id,
                'leg_role': 'entry',
                'leg_state': 'sending',
                'broker': 'flattrade',
                'tag_sent': 'callerTag',
                'identifier_sent': 'RELIANCE-EQ',
                'quantity': 10,
                'price': 1000,
            },
            {
                'time': '2026-09-23T10:00:02+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 3,
                'event': 'leg_answered',
                'leg_id': leg_id,
                'leg_state': 'acknowledged',
                'broker_order_id': '26091500000021',
                'outcome': 'accepted',
            },
            {
                'time': '2026-09-23T10:00:03+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 4,
                'event': 'parent_state_changed',
                'parent_state': 'working',
            },
            {
                'time': '2026-09-23T10:00:09+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 5,
                'event': 'leg_update',
                'leg_id': leg_id,
                'leg_state': 'filled',
                'filled_quantity': 10,
                'average_price': 999.75,
            },
            {
                'time': '2026-09-23T10:00:09+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 6,
                'event': 'parent_state_changed',
                'parent_state': 'completed',
            },
        ]

    def run_parent_checks(self):
        """Replays recorded transitions through the state machine, which does no I/O at all.

        Returns:
            list: One recorded result per check.
        """
        results = []
        events = self.parent_events()

        parent = ParentOrder.from_events(events)
        results.append({
            'name': 'a_plain_order_replays_to_completed',
            'state': parent.state,
            'terminal': parent.is_terminal(),
            'sequence': parent.sequence,
            'tag': parent.tag,
            'parent_tag': parent.parent_tag,
            'legs': [leg.document() for leg in parent.legs],
            'filled_quantity': parent.filled_quantity(),
        })

        replayed_twice = ParentOrder.from_events(events + events)
        results.append({
            'name': 'a_transition_recorded_twice_changes_nothing',
            'same_as_once': replayed_twice.document() == parent.document(),
            'legs': len(replayed_twice.legs),
            'sequence': replayed_twice.sequence,
        })

        halfway = ParentOrder.from_events(events[:2])
        results.append({
            'name': 'a_crash_after_requesting_leaves_the_leg_in_sending',
            'state': halfway.state,
            'terminal': halfway.is_terminal(),
            'leg_states': [leg.state for leg in halfway.legs],
            'leg_has_broker_order_id': bool(halfway.legs[0].broker_order_id),
            'leg_is_live': halfway.legs[0].is_live(),
            'leg_is_finished': halfway.legs[0].is_finished(),
        })

        rebuilt = ParentOrder.from_document(parent.document())
        results.append({
            'name': 'a_parent_survives_the_redis_round_trip',
            'same_document': rebuilt.document() == parent.document(),
            'state': rebuilt.state,
            'legs': len(rebuilt.legs),
        })

        abandoned = ParentOrder.from_events(events[:2] + [
            {
                'time': '2026-09-23T10:00:30+00:00',
                'parent_order_id': events[0]['parent_order_id'],
                'sequence': 3,
                'event': 'orphan_abandoned',
                'parent_state': 'failed',
                'leg_id': events[1]['leg_id'],
                'leg_state': 'unknown',
                'status_message': 'no order at the broker matches what was sent',
            },
        ])
        results.append({
            'name': 'an_abandoned_orphan_replays_as_a_finished_parent',
            'state': abandoned.state,
            'terminal': abandoned.is_terminal(),
            'leg_states': [leg.state for leg in abandoned.legs],
            'last_error': abandoned.last_error,
        })

        fresh = ParentOrder('11111111-2222-4333-8444-555555555555')
        results.append({
            'name': 'the_state_machine_refuses_a_change_it_does_not_allow',
            'received_to_working': fresh.can_change_to('working'),
            'received_to_protecting': fresh.can_change_to('protecting'),
            'received_to_completed': fresh.can_change_to('completed'),
            'completed_to_anything': ParentOrder.from_events(events).can_change_to('working'),
            'next_sequence': fresh.next_sequence(),
            'next_leg_id': fresh.next_leg_id(),
        })
        return results

    def crashed_events(self, leg_state='sending'):
        """The transitions a crash between recording an order and hearing the answer leaves behind.

        Args:
            leg_state (str): The state the leg was left in.

        Returns:
            list: The events, oldest first.
        """
        parent_order_id = '99999999-8888-4777-8666-555555555555'
        return [
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': '11111111-1111-5111-8111-000000000001',
                'detail': {
                    'body': {
                        'quantity': 10,
                    },
                },
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': parent_order_id,
                'sequence': 2,
                'event': 'leg_requested',
                'leg_id': f'{parent_order_id}:1',
                'leg_role': 'entry',
                'leg_state': leg_state,
                'broker': 'flattrade',
                'identifier_sent': 'RELIANCE-flattrade',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 1000,
            },
        ]

    def book_order(self, **overrides):
        """One order in a broker's book, matching what the crashed leg sent unless overridden.

        Args:
            **overrides: Fields to replace on the order.

        Returns:
            str: The entry as Redis holds it.
        """
        order = {
            'order_id': '26091500000021',
            'status': 'OPEN',
            'tradingsymbol': 'RELIANCE-flattrade',
            'instrument_token': '2885',
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'validity': 'DAY',
            'quantity': 10,
            'filled_quantity': 0,
            'price': 1000,
            'trigger_price': None,
            'average_price': None,
            'tag': None,
            'order_timestamp': '2026-09-23T10:00:02+00:00',
        }
        order.update(overrides)
        return json.dumps({
            'observed_at': 1790000000.0,
            'source': 'rest',
            'order': order,
            'data': {},
        })

    def recovery_result(self, name, events, book, polled_ago=5.0):
        """Runs recovery once against a fresh stand-in and records what it decided.

        Args:
            name (str): The check's name.
            events (list): The transitions already recorded.
            book (dict): Flattrade's order book entries, by the broker's order id.
            polled_ago (float): How long ago that book was last read, in seconds.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        self.fake_redis.hashes['flattrade:orders:orders'] = dict(book)
        self.fake_redis.strings['flattrade:orders:orders:polled_at'] = str(
            time.time() - polled_ago,
        )
        event_log = RecordingEventLog()
        event_log.events = [dict(event) for event in events]
        logger = logging.getLogger('test_runs.order_engine')
        parent_store = ParentStore(self.fake_redis)
        recovery = EngineRecovery(
            self.fake_redis,
            event_log,
            parent_store,
            order_routes.BROKER_NAMES,
            logger,
        )
        counts = recovery.recover()
        # What recovery wrote to Redis, not a fresh replay of the events: the replay would discard
        # every reconciliation recovery just made, which is the thing being checked.
        stored = self.fake_redis.hashes.get('unified:orders:parents', {})
        parents = [
            ParentOrder.from_document(json.loads(document))
            for document in stored.values()
        ]
        return {
            'name': name,
            'counts': counts,
            'parent_states': [parent.state for parent in parents],
            'leg_states': [
                leg.state for parent in parents for leg in parent.legs
            ],
            'leg_order_ids': [
                leg.broker_order_id
                for parent in parents
                for leg in parent.legs
            ],
            'leg_filled': [
                leg.filled_quantity
                for parent in parents
                for leg in parent.legs
            ],
            'recorded_after': [
                {
                    'event': event['event'],
                    'leg_state': event.get('leg_state'),
                    'parent_state': event.get('parent_state'),
                    'status_message': event.get('status_message'),
                    'candidates': (event.get('detail') or {}).get('candidates'),
                }
                for event in event_log.events[len(events):]
            ],
            'open_parents': len(
                self.fake_redis.sets.get('unified:orders:parents:open', set()),
            ),
        }

    def followed_parent(self):
        """A parent with one acknowledged leg, as the store would hold it after a placement.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder.from_events([
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': '44444444-3333-4222-8111-000000000000',
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'working',
                'instrument_id': '11111111-1111-5111-8111-000000000001',
                'detail': {
                    'body': {
                        'quantity': 10,
                    },
                },
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': '44444444-3333-4222-8111-000000000000',
                'sequence': 2,
                'event': 'leg_answered',
                'leg_id': '44444444-3333-4222-8111-000000000000:1',
                'leg_role': 'entry',
                'leg_state': 'acknowledged',
                'broker': 'flattrade',
                'broker_order_id': '26091500000021',
                'quantity': 10,
            },
        ])
        return parent

    def follower_result(self, name, update):
        """Applies one order update to a stored parent and records what changed.

        Args:
            name (str): The check's name.
            update (dict): The update, on the order contract.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        parent_store = ParentStore(self.fake_redis)
        parent = self.followed_parent()
        parent_store.save(parent)
        event_log = RecordingEventLog()
        follower = OrderUpdateFollower(
            parent_store,
            event_log,
            logging.getLogger('test_runs.order_engine'),
        )
        changed = follower.follow({
            'update': json.dumps(update),
        })
        if changed is not None:
            parent_store.save(changed)
        stored = ParentOrder.from_document(
            parent_store.parent(parent.parent_order_id),
        )
        return {
            'name': name,
            'followed': follower.followed,
            'ignored': follower.ignored,
            'leg_state': stored.legs[0].state,
            'leg_filled': stored.legs[0].filled_quantity,
            'leg_average_price': stored.legs[0].average_price,
            'events': [
                {
                    'event': event['event'],
                    'leg_state': event.get('leg_state'),
                    'filled_quantity': event.get('filled_quantity'),
                    'average_price': event.get('average_price'),
                }
                for event in event_log.events
            ],
        }

    def run_follower_checks(self):
        """Applies the brokers' order updates to a leg the engine owns, and to ones it does not.

        Returns:
            list: One recorded result per check.
        """
        ours = {
            'broker': 'flattrade',
            'order_id': '26091500000021',
            'status': 'COMPLETE',
            'filled_quantity': 10,
            'average_price': 999.25,
        }
        return [
            self.follower_result('a_fill_moves_the_leg_and_is_recorded', ours),
            self.follower_result(
                'a_partial_fill_is_recorded_without_finishing_the_leg',
                dict(ours, status='OPEN', filled_quantity=4, average_price=999.0),
            ),
            self.follower_result(
                'an_update_for_another_order_is_ignored',
                dict(ours, order_id='99999999999999'),
            ),
            self.follower_result(
                'an_update_from_another_broker_is_ignored',
                dict(ours, broker='zerodha'),
            ),
            self.follower_result(
                'an_update_that_changes_nothing_is_not_recorded',
                {
                    'broker': 'flattrade',
                    'order_id': '26091500000021',
                    'status': 'OPEN',
                },
            ),
        ]

    def run_wiring_checks(self):
        """Checks the things a file move can quietly break without any test noticing.

        The event log's DDL path is computed by counting parents of its own file. Moving the module one directory deeper made that path point one level short, and nothing caught it, because the stand-in event log has no table to apply. The daemon failed on its first real start instead.

        Returns:
            list: One recorded result per check.
        """
        ddl_path = (
            synthetic_order_event_log.DDL_DIRECTORY
            / synthetic_order_event_log.DDL_FILE
        )
        return [
            {
                'name': 'the_event_table_ddl_is_where_the_log_looks_for_it',
                'exists': ddl_path.exists(),
                'relative_path': str(
                    ddl_path.relative_to(
                        pathlib.Path(__file__).resolve().parents[1],
                    ),
                ),
            },
        ]

    def run_recovery_checks(self):
        """Replays a crash and checks what recovery decides about the order it may have left behind.

        Returns:
            list: One recorded result per check.
        """
        crashed = self.crashed_events()
        results = []

        results.append(self.recovery_result(
            'one_matching_order_is_attributed',
            crashed,
            {
                '26091500000021': self.book_order(),
            },
        ))
        results.append(self.recovery_result(
            'no_matching_order_is_abandoned',
            crashed,
            {},
        ))
        results.append(self.recovery_result(
            'two_matching_orders_are_abandoned',
            crashed,
            {
                '26091500000021': self.book_order(),
                '26091500000022': self.book_order(
                    order_id='26091500000022',
                ),
            },
        ))
        results.append(self.recovery_result(
            'an_order_at_a_different_price_is_not_a_match',
            crashed,
            {
                '26091500000021': self.book_order(price=1001),
            },
        ))
        results.append(self.recovery_result(
            'an_order_with_another_tag_is_not_a_match',
            crashed,
            {
                '26091500000021': self.book_order(tag='someoneElse'),
            },
        ))
        results.append(self.recovery_result(
            'a_stale_broker_book_attributes_nothing',
            crashed,
            {
                '26091500000021': self.book_order(),
            },
            polled_ago=600.0,
        ))
        results.append(self.recovery_result(
            'a_live_leg_is_brought_up_to_date_from_the_book',
            crashed[:1] + [
                dict(
                    crashed[1],
                    leg_state='acknowledged',
                    broker_order_id='26091500000021',
                ),
            ],
            {
                '26091500000021': self.book_order(
                    status='COMPLETE',
                    filled_quantity=10,
                    average_price=999.5,
                ),
            },
        ))
        results.append(self.recovery_result(
            'a_leg_the_book_has_lost_becomes_unknown',
            crashed[:1] + [
                dict(
                    crashed[1],
                    leg_state='acknowledged',
                    broker_order_id='26091500000021',
                ),
            ],
            {},
        ))
        results.append(self.recovery_result(
            'a_finished_parent_is_left_alone',
            crashed + [
                {
                    'time': '2026-09-23T10:00:05+00:00',
                    'parent_order_id': crashed[0]['parent_order_id'],
                    'sequence': 3,
                    'event': 'parent_state_changed',
                    'parent_state': 'completed',
                },
            ],
            {
                '26091500000021': self.book_order(),
            },
        ))
        return results

    def run_every_scenario(self):
        """Runs every scenario with the broker network replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_request = requests.Session.request
        original_uuid4 = uuid.uuid4
        original_excluded = api_configuration['order_excluded_brokers']
        original_selector = api_configuration['order_broker_selector']
        requests.Session.request = self.network.request
        uuid.uuid4 = self.counting_uuid
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_broker_selector'] = 'round_robin'
        try:
            results = []
            for scenario in OrderEngineScenarios().build():
                results.append(self.run_scenario(scenario))
            results.extend(self.run_lock_checks())
            results.extend(self.run_parent_checks())
            results.extend(self.run_recovery_checks())
            results.extend(self.run_follower_checks())
            results.extend(self.run_wiring_checks())
        finally:
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
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
