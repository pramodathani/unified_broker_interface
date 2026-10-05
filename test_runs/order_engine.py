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
import datetime
import json
import logging
import pathlib
import re
import sys
import threading
import time
import uuid

import requests

from test_runs import engine_stand_ins
from test_runs import order_routes
from test_runs import redis_stand_ins
from unified_broker_interface.utilities.order_engine.utilities import engine_lock
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.book_reconciler import (
    BookReconciler,
)
from unified_broker_interface.utilities.order_engine.utilities.clock_ticker import (
    ClockTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    COUNT_KEY_PREFIX,
    DailyOrderCount,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    EngineLock,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
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
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    OrderUpdateFollower,
)
from unified_broker_interface.utilities.broker_orders.stoxkart import StoxkartOrders
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import OrderLeg
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_commands import (
    ParentCommands,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)
from unified_broker_interface.utilities.order_engine.utilities.price_ticker import (
    PriceTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)
from unified_broker_interface.utilities.order_engine.utilities.repricing_throttle import (
    RepricingThrottle,
)
from unified_broker_interface.utilities.order_engine.utilities.risk_gates import (
    RiskGates,
)
from unified_broker_interface.utilities.order_engine.utilities import (
    synthetic_order_event_log,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    VirtualBook,
)
from utilities.configurations import api_configuration

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent / 'fixtures' / 'order_engine.jsonl'
)
STALE_INTENT_SECONDS = 30.0
RESULT_TTL_SECONDS = 300
# A fixed moment in the middle of an Indian trading day, so a scenario naming a time of day means
# the same thing on every run and whatever timezone the machine keeps.
FROZEN_NOW = datetime.datetime(2026, 9, 23, 10, 0, 0, tzinfo=moments.INDIA)



class AcceptedModifyAnswer:
    """A broker's answer accepting a modification, for a check that intercepts `modify_leg`.

    Attributes:
        outcome (str): Always `accepted`.
        status_message (None): No message.
        response_body (dict): An empty body.
    """

    def __init__(self):
        """Builds the answer.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'accepted'
        self.status_message = None
        self.response_body = {}


class ModifyRecorder:
    """Stands in for `EnginePlacement.modify_leg`, remembering each change instead of sending it.

    Attributes:
        sent (list): One `(broker, order id, quantity)` per change.
    """

    def __init__(self):
        """Builds the recorder.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []

    def modify_leg(self, broker_name, broker_order_id, quantity=None, price=None, trigger_price=None):
        """Remembers one change and accepts it.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The order.
            quantity (int | None): The new quantity, in the broker's terms.
            price (decimal.Decimal | None): The new price, unused.
            trigger_price (decimal.Decimal | None): The new trigger, unused.

        Returns:
            AcceptedModifyAnswer: The answer.
        """
        del price
        del trigger_price
        self.sent.append((broker_name, broker_order_id, quantity))
        return AcceptedModifyAnswer()


class NumberingBrokerNetwork(order_routes.FakeBrokerNetwork):
    """The stubbed broker network, able to give each placed order its own Flattrade order id.

    An answer carrying `number_orders: true` has its `norenordno` replaced on every `PlaceOrder` by `26091500000101`, `26091500000102` and so on, so a type with several legs can be sent an update for one of them. An answer carrying `sequence`, a list of answers, answers each `PlaceOrder` with the next one in turn, the last repeating, so a type whose legs get different answers can be tested. Every other answer is exactly the stubbed one.

    Attributes:
        placed (int): How many orders have been numbered since the last reset.
    """

    def reset(self, answer):
        """Clears the captured requests and the numbering, and sets the answer for the next calls.

        Args:
            answer (dict | None): The answer, or None for an empty JSON object with HTTP 200.

        Returns:
            None: This method returns nothing.
        """
        super().reset(answer)
        self.placed = 0

    def request(self, method, url, **keyword_arguments):
        """Captures one outgoing request and answers it, numbering a placed order when the answer asks for it.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments: The remaining `requests` arguments.

        Returns:
            FakeResponse: The stubbed answer.
        """
        sequence = self.answer.get('sequence')
        if sequence and url.endswith('/PlaceOrder'):
            position = min(self.placed, len(sequence) - 1)
            self.placed = self.placed + 1
            stubbed = self.answer
            self.answer = sequence[position]
            try:
                return super().request(method, url, **keyword_arguments)
            finally:
                self.answer = stubbed
        if not self.answer.get('number_orders') or not url.endswith('/PlaceOrder'):
            return super().request(method, url, **keyword_arguments)
        self.placed = self.placed + 1
        stubbed = self.answer
        numbered = dict(stubbed)
        numbered['json'] = dict(stubbed.get('json') or {})
        numbered['json']['norenordno'] = str(26091500000100 + self.placed)
        self.answer = numbered
        try:
            return super().request(method, url, **keyword_arguments)
        finally:
            self.answer = stubbed

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
            **settings: Any other scenario keys, such as `answer`, `deadline_ago`, `passes` or `mapping_date` (the date `unified:catalogue:current_date` names instead of the one the catalogue was written under).

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
                'a_plain_order_naming_a_broker_goes_to_that_broker',
                [
                    dict(order, broker='fyers'),
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
                'an_expired_catalogue_is_refused_as_not_published',
                [
                    order,
                ],
                mapping_date='2026-09-14',
            ),
            self.intents(
                'an_intent_past_its_deadline_is_not_placed',
                [
                    order,
                ],
                deadline_ago=120.0,
            ),
            self.intents(
                'an_intent_that_already_started_a_parent_is_not_placed_again',
                [
                    order,
                ],
                started_intents={
                    f'{0:032x}': '44444444-3333-4222-8111-000000000000',
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_repeated_intent_past_its_deadline_is_answered_as_repeated',
                [
                    order,
                ],
                deadline_ago=120.0,
                started_intents={
                    f'{0:032x}': '44444444-3333-4222-8111-000000000000',
                },
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
                'an_entry_inside_the_exit_reserve_of_the_daily_cap_is_refused',
                [
                    order,
                ],
                gated=True,
                daily_caps={
                    'flattrade': 100,
                },
                daily_sent={
                    'flattrade': 95,
                },
            ),
            self.intents(
                'an_order_that_closes_a_position_may_use_the_exit_reserve',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        synthetic={
                            'type': 'simple',
                            'closes_position': True,
                        },
                    ),
                ],
                gated=True,
                daily_caps={
                    'flattrade': 100,
                },
                daily_sent={
                    'flattrade': 95,
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_exit_at_the_full_daily_cap_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        synthetic={
                            'type': 'simple',
                            'closes_position': True,
                        },
                    ),
                ],
                gated=True,
                daily_caps={
                    'flattrade': 100,
                },
                daily_sent={
                    'flattrade': 100,
                },
            ),
            self.intents(
                'a_broker_without_a_daily_cap_is_neither_counted_nor_refused',
                [
                    order,
                ],
                gated=True,
                daily_caps={
                    'zerodha': 10,
                },
                daily_sent={
                    'flattrade': 5000,
                },
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
                'a_reduce_only_sell_smaller_than_the_long_is_sent',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='SELL',
                        quantity=50,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': True,
                        },
                    ),
                ],
                positions=self.positions(75),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_reduce_only_buy_that_would_add_to_a_long_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='BUY',
                        quantity=10,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': True,
                        },
                    ),
                ],
                positions=self.positions(75),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_reduce_only_sell_larger_than_the_long_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='SELL',
                        quantity=100,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': True,
                        },
                    ),
                ],
                positions=self.positions(75),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_reduce_only_order_with_nothing_held_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='SELL',
                        quantity=10,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': True,
                        },
                    ),
                ],
                positions=self.positions(0),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_reduce_only_buy_back_of_a_short_is_sent',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='BUY',
                        quantity=40,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': True,
                        },
                    ),
                ],
                positions=self.positions(-40),
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_reduce_only_flag_that_is_not_true_or_false_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        transaction_type='SELL',
                        quantity=10,
                        synthetic={
                            'type': 'simple',
                            'reduce_only': 'yes',
                        },
                    ),
                ],
                positions=self.positions(75),
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
                'an_order_above_the_freeze_limit_is_split_in_whole_lots',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=120,
                        quantity=4125,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '3511',
                    },
                },
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'an_order_whose_lot_is_above_the_freeze_limit_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=120,
                        quantity=150,
                        synthetic={
                            'type': 'freeze_slicer',
                        },
                    ),
                ],
                instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                attributes={
                    'flattrade': {
                        'freeze_quantity': '50',
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
                'a_plan_order_below_the_freeze_limit_is_sent_whole',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=10,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'freeze_slicer': {},
                                        },
                                    ],
                                },
                            },
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
                'a_plan_order_above_the_freeze_limit_is_split_evenly',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=250,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'freeze_slicer': {},
                                        },
                                    ],
                                },
                            },
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
                'a_plan_every_slice_goes_to_the_same_broker',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=300,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'freeze_slicer': {},
                                        },
                                    ],
                                },
                            },
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
                'a_plan_broker_publishing_no_freeze_limit_sends_it_whole',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=250,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'freeze_slicer': {},
                                        },
                                    ],
                                },
                            },
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
                'a_plan_order_needing_too_many_slices_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        quantity=5000,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'freeze_slicer': {},
                                        },
                                    ],
                                },
                            },
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
                'a_plan_ladder_spreads_its_rungs_across_the_range',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=100,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'ladder': {
                                                'from_price': 995,
                                                'to_price': 1000,
                                                'steps': 3,
                                                'hold_limits': False,
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    ),
                ],
                answer=self.answers.json_answer(
                    200,
                    self.answers.place_success('flattrade'),
                ),
            ),
            self.intents(
                'a_plan_ladder_needs_a_quantity_for_every_rung',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=2,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'ladder': {
                                                'from_price': 995,
                                                'to_price': 1000,
                                                'steps': 5,
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    ),
                ],
            ),
            self.intents(
                'a_plan_ladder_with_one_step_is_refused',
                [
                    self.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=10,
                        synthetic={
                            'type': 'plan',
                            'plan': {
                                'order': {
                                    'presets': [
                                        {
                                            'ladder': {
                                                'from_price': 995,
                                                'to_price': 1000,
                                                'steps': 1,
                                            },
                                        },
                                    ],
                                },
                            },
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
        fake_redis (redis_stand_ins.FakeEngineStoreRedis): The stand-in the engine reads and writes.
        network (NumberingBrokerNetwork): The stubbed broker network.
    """

    def __init__(self):
        """Builds the suite with an empty stand-in and a stubbed network.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = redis_stand_ins.FakeEngineStoreRedis()
        self.network = NumberingBrokerNetwork()
        self.counting_uuid = engine_stand_ins.CountingUuid()
        self.scenarios = OrderEngineScenarios()

    def build_state(self):
        """Builds a stand-in holding the order routes' starting contents.

        Returns:
            redis_stand_ins.FakeEngineStoreRedis: The stand-in.
        """
        starting_state = order_routes.OrderRoutesState().build()
        fake_redis = redis_stand_ins.FakeEngineStoreRedis()
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
                self.fake_redis,
                scenario.get('rate_per_second', 0),
                scenario.get('rate_per_broker_per_second', 10),
                scenario.get('rate_wait_seconds', 0),
                logger,
            ),
            LossLockout(
                self.fake_redis,
                scenario.get('loss_limit', 0),
                logger,
            ),
            OrderToTradeRatio(),
            None,
            self.build_daily_count(scenario, logger),
        )

    def build_daily_count(self, scenario, logger):
        """The daily order count for one scenario, with the day's counts so far written to Redis, or None when it caps nothing.

        Args:
            scenario (dict): The scenario.
            logger (logging.Logger): The logger.

        Returns:
            DailyOrderCount | None: The count.
        """
        caps = scenario.get('daily_caps')
        if caps is None:
            return None
        daily_count = DailyOrderCount(self.fake_redis, caps, 0.05, logger)
        sent = scenario.get('daily_sent') or {}
        for broker_name, count in sent.items():
            self.fake_redis.strings[daily_count.key(broker_name)] = str(count)
        return daily_count

    def shown_daily_counts(self):
        """Every broker's daily order count in the stand-in Redis.

        Returns:
            dict: Each count (str), by key.
        """
        shown = {}
        for key in sorted(self.fake_redis.strings):
            if key.startswith(COUNT_KEY_PREFIX):
                shown[key] = self.fake_redis.strings[key]
        return shown

    def run_scenario(self, scenario, with_lanes=False):
        """Runs one scenario against a fresh stand-in and a fresh engine.

        Args:
            scenario (dict): The scenario.
            with_lanes (bool): Whether the engine hands every intent to a worker thread through a router with one worker, instead of placing it on the main thread.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = self.build_state()
        if scenario.get('mapping_date') is not None:
            self.fake_redis.strings['unified:catalogue:current_date'] = (
                scenario['mapping_date']
            )
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
                scenario.get(
                    'instrument_id',
                    order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                ): json.dumps(scenario['attributes']),
            }
        if scenario.get('positions') is not None:
            self.fake_redis.strings['unified:portfolio:positions'] = json.dumps(
                scenario['positions'],
            )
        if scenario.get('started_intents') is not None:
            self.fake_redis.hashes['unified:orders:parents:intents'] = dict(
                scenario['started_intents'],
            )
        self.network.reset(scenario.get('answer'))
        self.counting_uuid.reset()
        reply_keys = self.write_intents(scenario)

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        lock = EngineLock(self.fake_redis, logger)
        event_log = engine_stand_ins.RecordingEventLog()
        event_log.failing_event = scenario.get('failing_event')
        gates = self.build_gates(scenario, logger)
        if gates is not None:
            placement.order_placement.attach_daily_count(gates.daily_count)
        router = None
        if with_lanes:
            router = ParentRouter(
                [],
                {},
                1,
                logger,
            )
            router.start()
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
            router=router,
        )
        self.fake_redis.round_trips = 0
        exit_code = engine.run(engine_stand_ins.OnePassStop(scenario.get('passes', 3)))

        delivered = self.fake_redis.pending.get(INTENT_STREAM_KEY, [])
        result = {
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
        if scenario.get('daily_caps') is not None:
            result['daily_counts'] = self.shown_daily_counts()
        if engine.repeated:
            result['repeated'] = engine.repeated
        return result

    def run_lane_equivalence_check(self):
        """Runs every intent scenario again with one worker thread behind a router, and compares it with the main-thread run.

        Everything must match except the Redis round trips, since intake reads the credentials and the instrument to choose the broker before handing the intent to its worker.

        Returns:
            dict: The recorded result: the scenarios compared, those that differed and in which fields, and how the round trips changed.
        """
        compared = 0
        differing = []
        round_trip_changes = {}
        for scenario in OrderEngineScenarios().build():
            on_main_thread = self.run_scenario(scenario)
            with_lanes = self.run_scenario(scenario, True)
            compared = compared + 1
            fields = []
            for field in sorted(set(on_main_thread) | set(with_lanes)):
                if field == 'redis_round_trips':
                    continue
                if on_main_thread.get(field) != with_lanes.get(field):
                    fields.append(field)
            if fields:
                differing.append({
                    'name': scenario['name'],
                    'fields': fields,
                })
            change = (
                with_lanes['redis_round_trips']
                - on_main_thread['redis_round_trips']
            )
            round_trip_changes[str(change)] = (
                round_trip_changes.get(str(change), 0) + 1
            )
        return {
            'name': 'lanes_give_the_same_answers_as_the_main_thread',
            'compared': compared,
            'differing': differing,
            'round_trip_changes': round_trip_changes,
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

    def recovery_result(self, name, events, book, polled_ago=5.0, first_pass=False):
        """Runs recovery once against a fresh stand-in and records what it decided.

        Args:
            name (str): The check's name.
            events (list): The transitions already recorded.
            book (dict): Flattrade's order book entries, by the broker's order id.
            polled_ago (float): How long ago that book was last read, in seconds.
            first_pass (bool): Whether the engine's first order book pass runs after recovery, as it does at start.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        self.fake_redis.hashes['flattrade:orders:orders'] = dict(book)
        self.fake_redis.strings['flattrade:orders:orders:polled_at'] = str(
            time.time() - polled_ago,
        )
        event_log = engine_stand_ins.RecordingEventLog()
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
        if first_pass:
            placement = EnginePlacement(self.fake_redis, logger)
            engine = OrderEngine(
                self.fake_redis,
                placement,
                EngineLock(self.fake_redis, logger),
                logger,
                STALE_INTENT_SECONDS,
                RESULT_TTL_SECONDS,
                event_log,
                parent_store,
                OrderUpdateFollower(
                    parent_store,
                    event_log,
                    logger,
                    None,
                    placement,
                ),
                reconciler=BookReconciler(self.fake_redis, parent_store, 0.0),
            )
            engine.reconcile_books()
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
        event_log = engine_stand_ins.RecordingEventLog()
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
            'held': follower.held,
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

    def finishing_result(self, name, synthetic_type, updates):
        """Delivers updates to a one-leg parent of a given type and records whether the parent ends.

        A `simple` parent whose order was cancelled through `DELETE /api/orders/cancel` stayed `working` in the live retest of 2026-09-27, because nothing finished it.

        Args:
            name (str): The check's name.
            synthetic_type (str): The parent's type.
            updates (list): The updates, on the order contract, in order.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        parent_store = ParentStore(self.fake_redis)
        parent = self.followed_parent()
        parent.synthetic_type = synthetic_type
        parent_store.save(parent)
        logger = logging.getLogger('test_runs.order_engine')
        follower = OrderUpdateFollower(
            parent_store,
            engine_stand_ins.RecordingEventLog(),
            logger,
            None,
            EnginePlacement(self.fake_redis, logger),
        )
        for update in updates:
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
            'synthetic_type': synthetic_type,
            'leg_state': stored.legs[0].state,
            'leg_filled': stored.legs[0].filled_quantity,
            'parent_state': stored.state,
        }

    def cancelling_parent_result(self, name, update):
        """Delivers an update for the last live leg of a parent that is `cancelling`, and records whether the parent ends.

        Args:
            name (str): The check's name.
            update (dict): The update, on the order contract.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        parent_store = ParentStore(self.fake_redis)
        parent = self.followed_parent()
        parent.state = 'cancelling'
        parent_store.save(parent)
        logger = logging.getLogger('test_runs.order_engine')
        follower = OrderUpdateFollower(
            parent_store,
            engine_stand_ins.RecordingEventLog(),
            logger,
            None,
            EnginePlacement(self.fake_redis, logger),
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
            'leg_state': stored.legs[0].state,
            'parent_state': stored.state,
            'sent': len(self.network.sent_requests),
        }

    def reconciled_result(self, name, parent_state, book_order, leg_filled=0):
        """Runs one reconciliation pass against a stored parent and a broker book, with no socket update at all.

        Args:
            name (str): The check's name.
            parent_state (str): The parent's state before the pass, such as `working` or `cancelling`.
            book_order (dict | None): Fields to set on the leg's book entry, or None for no entry.
            leg_filled (int): How much the leg already records as filled.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        parent_store = ParentStore(self.fake_redis)
        parent = self.followed_parent()
        parent.state = parent_state
        parent.legs[0].filled_quantity = leg_filled
        if leg_filled:
            parent.legs[0].state = 'partially_filled'
        parent_store.save(parent)
        if book_order is not None:
            book = self.fake_redis.hashes.setdefault(
                'flattrade:orders:orders',
                {},
            )
            book['26091500000021'] = self.broker_book_entry(
                '26091500000021',
                **book_order,
            )
        logger = logging.getLogger('test_runs.order_engine')
        event_log = engine_stand_ins.RecordingEventLog()
        placement = EnginePlacement(self.fake_redis, logger)
        reconciler = BookReconciler(self.fake_redis, parent_store, 5.0)
        engine = OrderEngine(
            self.fake_redis,
            placement,
            EngineLock(self.fake_redis, logger),
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            parent_store,
            OrderUpdateFollower(
                parent_store,
                event_log,
                logger,
                None,
                placement,
            ),
            reconciler=reconciler,
        )
        engine.reconcile_books()
        engine.reconcile_books()
        stored = ParentOrder.from_document(
            parent_store.parent(parent.parent_order_id),
        )
        return {
            'name': name,
            'found': reconciler.found,
            'leg_state': stored.legs[0].state,
            'leg_filled': stored.legs[0].filled_quantity,
            'parent_state': stored.state,
            'still_open': parent.parent_order_id in self.fake_redis.sets.get(
                'unified:orders:parents:open',
                set(),
            ),
        }

    def reconciler_due_result(self, name, interval_seconds, elapsed_seconds):
        """Records whether a reconciliation pass is due.

        Args:
            name (str): The check's name.
            interval_seconds (float): The configured interval.
            elapsed_seconds (float): How long ago the last pass ran.

        Returns:
            dict: The recorded result.
        """
        reconciler = BookReconciler(None, None, interval_seconds)
        return {
            'name': name,
            'due': reconciler.due(reconciler.checked_at + elapsed_seconds),
        }

    def early_update_result(self, name, registered_before_replay, hold_seconds):
        """Delivers a fill before its order is registered, then replays the held updates.

        Args:
            name (str): The check's name.
            registered_before_replay (bool): Whether the parent is saved, registering its order, between the fill and the replay.
            hold_seconds (float): How long the follower holds an unknown update.

        Returns:
            dict: The recorded result.
        """
        self.fake_redis = self.build_state()
        parent_store = ParentStore(self.fake_redis)
        parent = self.followed_parent()
        event_log = engine_stand_ins.RecordingEventLog()
        follower = OrderUpdateFollower(
            parent_store,
            event_log,
            logging.getLogger('test_runs.order_engine'),
        )
        follower.early_updates.hold_seconds = hold_seconds
        first = follower.follow({
            'update': json.dumps({
                'broker': 'flattrade',
                'order_id': '26091500000021',
                'status': 'OPEN',
                'filled_quantity': 4,
                'average_price': 999.0,
            }),
        })
        second = follower.follow({
            'update': json.dumps({
                'broker': 'flattrade',
                'order_id': '26091500000021',
                'status': 'COMPLETE',
                'filled_quantity': 10,
                'average_price': 999.25,
            }),
        })
        if registered_before_replay:
            parent_store.save(parent)
        replayed_parents = follower.replay_early_updates()
        for replayed_parent in replayed_parents:
            parent_store.save(replayed_parent)
        stored_document = parent_store.parent(parent.parent_order_id)
        leg_state = None
        leg_filled = None
        if stored_document is not None:
            stored = ParentOrder.from_document(stored_document)
            leg_state = stored.legs[0].state
            leg_filled = stored.legs[0].filled_quantity
        return {
            'name': name,
            'applied_on_arrival': [
                first is not None,
                second is not None,
            ],
            'held': follower.held,
            'replayed': follower.replayed,
            'dropped': follower.early_updates.dropped,
            'still_held': len(follower.early_updates.held),
            'leg_state': leg_state,
            'leg_filled': leg_filled,
            'events': [
                {
                    'event': event['event'],
                    'leg_state': event.get('leg_state'),
                    'filled_quantity': event.get('filled_quantity'),
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
                'an_update_for_another_order_is_held_and_not_applied',
                dict(ours, order_id='99999999999999'),
            ),
            self.follower_result(
                'an_update_from_another_broker_is_held_and_not_applied',
                dict(ours, broker='zerodha'),
            ),
            self.early_update_result(
                'fills_that_arrive_before_their_order_is_known_are_applied_in_order_once_it_is',
                True,
                30.0,
            ),
            self.early_update_result(
                'an_early_update_whose_order_never_becomes_known_is_dropped',
                False,
                0.0,
            ),
            self.finishing_result(
                'a_simple_parent_completes_when_its_order_fills',
                'simple',
                [
                    dict(ours, status='COMPLETE', filled_quantity=10),
                ],
            ),
            self.finishing_result(
                'a_simple_parent_is_cancelled_when_its_order_is_cancelled',
                'simple',
                [
                    dict(ours, status='CANCELLED', filled_quantity=0),
                ],
            ),
            self.finishing_result(
                'a_simple_parent_that_traded_before_its_cancel_completes',
                'simple',
                [
                    dict(ours, status='OPEN', filled_quantity=4, average_price=999.0),
                    dict(ours, status='CANCELLED', filled_quantity=4, average_price=999.0),
                ],
            ),
            self.finishing_result(
                'a_simple_parent_stays_open_while_its_order_rests',
                'simple',
                [
                    dict(ours, status='OPEN', filled_quantity=4, average_price=999.0),
                ],
            ),
            self.finishing_result(
                'a_strategy_stop_keeps_watching_after_its_orders_fill',
                'strategy_stop',
                [
                    dict(ours, status='COMPLETE', filled_quantity=10),
                ],
            ),
            self.cancelling_parent_result(
                'a_cancelling_parent_ends_when_its_last_leg_is_cancelled',
                dict(ours, status='CANCELLED', filled_quantity=0),
            ),
            self.cancelling_parent_result(
                'a_cancelling_parent_waits_while_its_leg_is_still_open',
                dict(ours, status='OPEN', filled_quantity=0),
            ),
            self.reconciled_result(
                'a_cancel_only_the_polled_book_shows_finishes_the_parent',
                'working',
                {
                    'status': 'CANCELLED',
                },
            ),
            self.reconciled_result(
                'a_fill_only_the_polled_book_shows_completes_the_parent',
                'working',
                {
                    'status': 'COMPLETE',
                    'quantity': 10,
                    'filled_quantity': 10,
                    'average_price': 1009.5,
                },
            ),
            self.reconciled_result(
                'a_cancelling_parent_ends_when_the_polled_book_shows_its_cancel',
                'cancelling',
                {
                    'status': 'CANCELLED',
                },
            ),
            self.reconciled_result(
                'a_partial_fill_only_the_polled_book_shows_is_recorded',
                'working',
                {
                    'status': 'OPEN',
                    'filled_quantity': 4,
                },
            ),
            self.reconciled_result(
                'a_polled_book_behind_the_socket_changes_nothing',
                'working',
                {
                    'status': 'OPEN',
                    'filled_quantity': 2,
                },
                4,
            ),
            self.reconciled_result(
                'a_resting_order_in_the_polled_book_changes_nothing',
                'working',
                {
                    'status': 'OPEN',
                },
            ),
            self.reconciled_result(
                'an_order_missing_from_the_polled_book_changes_nothing',
                'working',
                None,
            ),
            self.reconciler_due_result(
                'reconciliation_waits_for_its_interval',
                5.0,
                4.0,
            ),
            self.reconciler_due_result(
                'reconciliation_runs_once_its_interval_has_passed',
                5.0,
                5.0,
            ),
            self.reconciler_due_result(
                'reconciliation_is_off_when_its_interval_is_zero',
                0.0,
                100.0,
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

    def broker_book_entry(self, order_id, status='OPEN', **overrides):
        """One entry in Flattrade's order book, which a cancel or a change is built from.

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
            # The real order book carries the exchange as well as the symbol, and a broker's modify
            # builder refuses without it rather than guessing. Leaving it out of this fixture is
            # how the reduction scenarios first came back doing nothing at all.
            'exchange': 'NSE',
            'tradingsymbol': 'RELIANCE-flattrade',
            'instrument_token': '1',
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'validity': 'DAY',
            'quantity': 10,
            'filled_quantity': 0,
            'price': 1010,
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

    def reaction_result(
        self,
        name,
        body,
        updates,
        answer=None,
        gated=False,
        quote=None,
        positions=None,
    ):
        """Places one order through the engine, then feeds it order updates and records what it does.

        This is the only place the two halves of the engine run together: the intent loop places the
        first leg, and the follower then hands each update to the order type, which may place, cancel
        or reduce other legs. Every broker request is kept in the order it was sent.

        Args:
            name (str): The check's name.
            body (dict): The request body.
            updates (list): One order update per step, applied in order.
            answer (dict | None): The stubbed broker answer.
            gated (int | bool): How many requests a second the rate budget allows, or False for no budget.
            quote (dict | None): A live quote to seed, for a type that reads the book when it is placed.
            positions (float | None): A net position in RELIANCE to seed, for an order that protects one.

        Returns:
            dict: The recorded result.
        """
        scenario = self.scenarios.intents(name, [body], answer=answer)
        self.fake_redis = self.build_state()
        if quote is not None:
            self.seed_quote(quote)
        if positions is not None:
            self.seed_positions(positions)
        self.network.reset(answer)
        self.counting_uuid.reset()
        reply_keys = self.write_intents(scenario)

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        event_log = engine_stand_ins.RecordingEventLog()
        parent_store = ParentStore(self.fake_redis)
        gates = None
        if gated:
            gates = RiskGates(
                RateBudget(self.fake_redis, gated, gated, 0, logger),
                LossLockout(self.fake_redis, 0, logger),
                OrderToTradeRatio(),
            )
        engine = OrderEngine(
            self.fake_redis,
            placement,
            EngineLock(self.fake_redis, logger),
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            parent_store,
            None,
            gates,
        )
        engine.run(engine_stand_ins.OnePassStop(3))

        follower = OrderUpdateFollower(
            parent_store,
            event_log,
            logger,
            gates,
            placement,
        )
        for update in updates:
            # The broker's own book has to hold the order before a cancel or a change can be built
            # from it, exactly as it does in life.
            book = self.fake_redis.hashes.setdefault(
                'flattrade:orders:orders',
                {},
            )
            book[str(update['order_id'])] = self.broker_book_entry(
                str(update['order_id']),
                status=update.get('status', 'OPEN'),
            )
            changed = follower.follow({
                'update': json.dumps(update),
            })
            if changed is not None:
                parent_store.save(changed)

        stored = list(
            self.fake_redis.hashes.get('unified:orders:parents', {}).values(),
        )
        parents = [ParentOrder.from_document(json.loads(one)) for one in stored]
        return {
            'name': name,
            'reply': self.shown_replies(reply_keys)[0],
            'sent': [
                {
                    'url': request['url'].rsplit('/', 1)[-1],
                    'quantity': self.sent_quantity(request),
                }
                for request in self.network.sent_requests
            ],
            'events': [event['event'] for event in event_log.events],
            'legs': [
                {
                    'role': leg.role,
                    'state': leg.state,
                    'quantity': leg.quantity,
                    'filled': leg.filled_quantity,
                }
                for parent in parents
                for leg in parent.legs
            ],
            'parent_states': [parent.state for parent in parents],
            'followed': follower.followed,
            'reacted': follower.reacted,
            'gates': gates.counts() if gates is not None else None,
        }

    def sent_quantity(self, request):
        """The quantity one captured broker request carries, where it carries one.

        Args:
            request (dict): The captured request.

        Returns:
            str | None: The quantity.
        """
        form = request.get('data') or ''
        found = re.search(r'"qty": "([^"]*)"', form)
        return found.group(1) if found else None

    def update(self, order_id, status, filled, **overrides):
        """One order update on the unified contract.

        Args:
            order_id (str): The broker's order id.
            status (str): The status on the shared vocabulary.
            filled (int): The filled quantity.
            **overrides: Other fields.

        Returns:
            dict: The update.
        """
        document = {
            'broker': 'flattrade',
            'order_id': order_id,
            'status': status,
            'filled_quantity': filled,
            'average_price': 1000.0,
        }
        document.update(overrides)
        return document

    def plan_result(self, name, plan, updates, answer, dry_run=None, quote=None, body_overrides=None):
        """Places one `plan` order through the engine, feeds it order updates, and records what it did and the state of each of its parts.

        Args:
            name (str): The check's name.
            plan (object): The `plan` object, as a caller would send it.
            updates (list): One order update per step, applied in order.
            answer (dict): The stubbed broker answer.
            dry_run (bool | None): The body's `dry_run`.
            quote (dict | None): A live quote to seed, for a plan that reads the book when it is placed.
            body_overrides (dict | None): Body fields to replace, such as the quantity.

        Returns:
            dict: The recorded result, with `parts`, each parent's `parts` parameter.
        """
        body = self.scenarios.bodies.market_order(
            dry_run=dry_run,
            order_type='LIMIT',
            price=1000,
            quantity=10,
            synthetic={
                'type': 'plan',
                'plan': plan,
            },
        )
        if body_overrides:
            body.update(body_overrides)
        result = self.reaction_result(name, body, updates, answer, quote=quote)
        stored = self.fake_redis.hashes.get('unified:orders:parents', {})
        parts = []
        for document in stored.values():
            parameters = json.loads(document).get('parameters') or {}
            parts.append(parameters.get('parts'))
        result['parts'] = parts
        return result

    def run_plan_checks(self):
        """Runs the `plan` type, the first stage of the composable orders, through placement, fills, refusals and a dry run.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        rejected = self.scenarios.answers.json_answer(
            200,
            {
                'stat': 'Not_Ok',
                'emsg': 'RMS:Margin Exceeds',
            },
        )
        one_simple_order = {
            'order': {
                'presets': [
                    {
                        'simple': {},
                    },
                ],
            },
        }
        return [
            self.plan_result(
                'a_plan_of_one_simple_order_completes_when_it_fills',
                one_simple_order,
                [
                    self.update('26091500000021', 'OPEN', 4),
                    self.update('26091500000021', 'COMPLETE', 10),
                ],
                accepted,
            ),
            self.plan_result(
                'a_plan_order_cancelled_after_part_filled_completes_as_partly_filled',
                one_simple_order,
                [
                    self.update('26091500000021', 'OPEN', 4),
                    self.update('26091500000021', 'CANCELLED', 4),
                ],
                accepted,
            ),
            self.plan_result(
                'a_plan_order_the_broker_rejects_is_done_as_refused',
                one_simple_order,
                [],
                rejected,
            ),
            self.plan_result(
                'a_plan_with_no_presets_runs_as_a_simple_order',
                {
                    'order': {},
                },
                [],
                accepted,
            ),
            self.plan_result(
                'a_plan_dry_run_answers_with_the_expanded_plan_and_records_nothing',
                one_simple_order,
                [],
                accepted,
                dry_run=True,
            ),
            self.plan_result(
                'a_plan_with_a_join_is_refused_as_not_built_yet',
                {
                    'together': {},
                },
                [],
                accepted,
            ),
            self.plan_result(
                'a_plan_lists_every_problem_at_once',
                {
                    'order': {
                        'side': 'long',
                        'presets': [
                            {
                                'no_such_preset': {},
                            },
                            {
                                'simple': {
                                    'broker': 'zerodha',
                                },
                            },
                        ],
                    },
                },
                [],
                accepted,
            ),
            self.plan_result(
                'a_plan_that_is_not_an_object_is_refused',
                'buy 10',
                [],
                accepted,
            ),
        ]

    def plan_clock_result(self, name, plan, fills, tick_at, answer, quote=None, taken_at=None, positions=None, resting=None, body_overrides=None, record_prices=False):
        """Places one `plan` order, optionally fills it, gives it two clock ticks, and records what it did and the state of each of its parts.

        Args:
            name (str): The check's name.
            plan (object): The `plan` object, as a caller would send it.
            fills (list): Order updates to apply before the tick.
            tick_at (float): The Unix time to tick at.
            answer (dict): The stubbed broker answer.
            quote (dict | None): A live quote to seed, for an order made marketable when it ends.
            taken_at (datetime.datetime | None): The moment the engine takes the order, or None for `FROZEN_NOW`.
            positions (float | dict | None): A net RELIANCE position to seed, or each broker's share, or None for none.
            resting (list | None): Flattrade order ids of open RELIANCE orders placed outside the engine.
            body_overrides (dict | None): Body fields to replace, such as the quantity and price.
            record_prices (bool): Whether to record the price of every leg placed, as `leg_prices`.

        Returns:
            dict: The recorded result, with `parts`, each parent's `parts` parameter.
        """
        body = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
            synthetic={
                'type': 'plan',
                'plan': plan,
            },
        )
        if body_overrides:
            body.update(body_overrides)
        result = self.clock_result(name, body, fills, tick_at, answer, quote=quote, taken_at=taken_at, positions=positions, resting=resting)
        stored = self.fake_redis.hashes.get('unified:orders:parents', {})
        parts = []
        prices = []
        for document in stored.values():
            parameters = json.loads(document).get('parameters') or {}
            parts.append(parameters.get('parts'))
            for leg in ParentOrder.from_document(json.loads(document)).legs:
                prices.append(leg.price)
        result['parts'] = parts
        if record_prices:
            result['leg_prices'] = prices
        return result

    def plan_price_result(self, name, plan, steps, answer, positions=None, restart_between_ticks=False, book_overrides=None, transaction_type='BUY', body_overrides=None, resting=None):
        """Places one `plan` order and walks it through price ticks, recording what it did and the state of each of its parts.

        Args:
            name (str): The check's name.
            plan (object): The `plan` object, as a caller would send it.
            steps (list): One tick per step, as `price_result` takes them.
            answer (dict): The stubbed broker answer.
            positions (float | None): A net RELIANCE position to seed, or None for none.
            restart_between_ticks (bool): Whether to rebuild every parent from its recorded events after each tick, as recovery does.
            book_overrides (dict | None): Fields to put on every order in the broker's book, such as a stop's order type.
            transaction_type (str): The body's side, as a caller sent it; the API accepts it in any case.
            body_overrides (dict | None): Body fields to replace, such as another instrument, quantity and price.
            resting (list | None): Flattrade order ids of open RELIANCE orders placed outside the engine, for an order that cancels what is resting.

        Returns:
            dict: The recorded result, with `parts`, each parent's `parts` parameter.
        """
        body = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
            synthetic={
                'type': 'plan',
                'plan': plan,
            },
        )
        body['transaction_type'] = transaction_type
        if body_overrides:
            body.update(body_overrides)
        result = self.price_result(
            name,
            body,
            steps,
            answer,
            positions=positions,
            restart_between_ticks=restart_between_ticks,
            book_every_order=True,
            book_overrides=book_overrides,
            resting=resting,
        )
        stored = self.fake_redis.hashes.get('unified:orders:parents', {})
        parts = []
        for document in stored.values():
            parameters = json.loads(document).get('parameters') or {}
            parts.append(parameters.get('parts'))
        result['parts'] = parts
        return result

    def run_plan_routing_checks(self):
        """Runs today's requests for three fixed types with the switch-over routing them to plans, beside the same requests run by the fixed types, and checks that the `closes_position` and `reduce_only` flags survive the routing; holding is turned off, so the routed orders send what the fixed types send.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        steady = self.book_at(1000.00, 1000.05)
        original_hold_limits = api_configuration['order_hold_limits']
        api_configuration['order_hold_limits'] = False
        try:
            return [
                self.reaction_result(
                    'a_routed_grid_replaces_a_filled_rung_with_its_opposite',
                    self.scenarios.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=5,
                        synthetic={
                            'type': 'grid',
                            'levels': 2,
                            'step_points': 5,
                            'most_inventory': 20,
                        },
                    ),
                    [
                        self.update('26091500000021', 'COMPLETE', 5),
                    ],
                    accepted,
                    quote=self.scenarios.quote(),
                ),
                self.reaction_result(
                    'a_routed_bracket_grows_its_exits_as_the_entry_fills_further',
                    self.scenarios.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=10,
                        synthetic={
                            'type': 'bracket',
                            'stop_price': 990,
                            'stop_limit_price': 988,
                            'target_price': 1010,
                        },
                    ),
                    [
                        self.update('26091500000021', 'OPEN', 4),
                        self.update('26091500000021', 'COMPLETE', 10),
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_market_if_touched_order_waits_and_then_takes_the_offer',
                    dict(entry, synthetic={
                        'type': 'market_if_touched',
                        'trigger_price': 995,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': self.book_at(994.90, 994.95), 'at': 1},
                        {'quote': self.book_at(994.90, 994.95), 'at': 2},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_market_if_touched_order_keeps_closes_position_beside_the_plan',
                    dict(entry, synthetic={
                        'type': 'market_if_touched',
                        'trigger_price': 995,
                        'closes_position': True,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': self.book_at(994.90, 994.95), 'at': 1},
                        {'quote': self.book_at(994.90, 994.95), 'at': 2},
                    ],
                    accepted,
                ),
                self.reaction_result(
                    'a_routed_oto_reads_a_lower_case_then_as_a_stop_sell',
                    self.scenarios.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=10,
                        synthetic={
                            'type': 'oto',
                            'then': {
                                'transaction_type': 'sell',
                                'order_type': 'sl',
                                'trigger_price': 990,
                                'price': 988,
                            },
                        },
                    ),
                    [
                        self.update('26091500000021', 'COMPLETE', 10),
                    ],
                    accepted,
                ),
                self.reaction_result(
                    'a_routed_oto_refuses_a_stop_market_then',
                    self.scenarios.bodies.market_order(
                        dry_run=None,
                        order_type='LIMIT',
                        price=1000,
                        quantity=10,
                        synthetic={
                            'type': 'oto',
                            'then': {
                                'transaction_type': 'sell',
                                'order_type': 'sl-m',
                                'trigger_price': 990,
                            },
                        },
                    ),
                    [],
                    accepted,
                ),
                self.price_result(
                    'a_routed_market_if_touched_order_keeps_reduce_only_beside_the_plan',
                    dict(entry, synthetic={
                        'type': 'market_if_touched',
                        'trigger_price': 995,
                        'reduce_only': True,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': self.book_at(994.90, 994.95), 'at': 1},
                        {'quote': self.book_at(994.90, 994.95), 'at': 2},
                    ],
                    accepted,
                ),
            ]
        finally:
            api_configuration['order_hold_limits'] = original_hold_limits

    def run_plan_held_ladder_checks(self):
        """Runs ladders whose rungs are held in the engine until the offer reaches each one, as plans and as the routed `ladder` type, with holding on and off.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        ladder_settings = {
            'from_price': 1000,
            'to_price': 995,
            'steps': 3,
        }
        held_ladder = {
            'order': {
                'presets': [
                    {
                        'ladder': dict(ladder_settings),
                    },
                ],
                'hold_limits': True,
            },
        }
        falling = [
            {'quote': steady, 'at': 0},
            {'quote': self.book_at(999.95, 1000.00), 'at': 1},
            {'quote': self.book_at(997.45, 997.50), 'at': 2},
            {'quote': self.book_at(997.40, 997.45), 'at': 3},
        ]
        nine = {
            'quantity': 9,
        }
        results = [
            self.plan_price_result(
                'a_plan_ladder_holds_each_rung_until_the_offer_reaches_its_price',
                held_ladder,
                falling,
                accepted,
                body_overrides=nine,
            ),
            self.plan_price_result(
                'a_plan_held_ladder_keeps_its_rungs_across_a_restart',
                held_ladder,
                falling,
                accepted,
                restart_between_ticks=True,
                body_overrides=nine,
            ),
            self.plan_price_result(
                'a_plan_held_ladder_sends_at_once_the_rungs_the_offer_is_already_past',
                held_ladder,
                [
                    {'quote': self.book_at(995.95, 996.00), 'at': 0},
                    {'quote': self.book_at(995.95, 996.00), 'at': 1},
                ],
                accepted,
                body_overrides=nine,
            ),
            self.plan_price_result(
                'a_plan_held_ladder_rung_changed_while_held_sends_its_new_price_and_quantity',
                held_ladder,
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'held_change': {
                            'part': 'root.pieces.1',
                            'price': '998',
                        },
                    },
                    {
                        'quote': self.book_at(997.95, 998.00),
                        'at': 2,
                        'held_change': {
                            'part': 'root.pieces.2',
                            'quantity': 5,
                        },
                    },
                    {'quote': self.book_at(994.95, 995.00), 'at': 3},
                ],
                accepted,
                body_overrides=nine,
            ),
            self.plan_price_result(
                'a_plan_held_ladder_refuses_a_post_only_guard',
                {
                    'order': {
                        'presets': [
                            {
                                'post_only': {},
                            },
                            {
                                'ladder': dict(ladder_settings),
                            },
                        ],
                        'hold_limits': True,
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides=nine,
            ),
            self.plan_price_result(
                'a_plan_ladder_refuses_a_hold_limits_that_is_not_true_or_false',
                {
                    'order': {
                        'presets': [
                            {
                                'ladder': dict(ladder_settings, hold_limits='no'),
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides=nine,
            ),
        ]
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=9,
        )
        results.append(
            self.price_result(
                'a_simple_order_refuses_hold_limits_true',
                dict(entry, synthetic={'type': 'simple', 'hold_limits': True}),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            )
        )
        original_hold_limits = api_configuration['order_hold_limits']
        api_configuration['order_hold_limits'] = True
        try:
            results.append(
                self.price_result(
                    'a_routed_ladder_holds_each_rung_until_the_offer_reaches_its_price',
                    dict(entry, synthetic=dict(ladder_settings, type='ladder')),
                    falling,
                    accepted,
                    book_every_order=True,
                )
            )
            results.append(
                self.price_result(
                    'a_routed_ladder_sends_every_rung_at_once_with_hold_limits_false',
                    dict(entry, synthetic=dict(ladder_settings, type='ladder', hold_limits=False)),
                    falling,
                    accepted,
                    book_every_order=True,
                )
            )
            api_configuration['order_hold_limits'] = False
            results.append(
                self.price_result(
                    'a_routed_ladder_sends_every_rung_at_once_when_holding_is_turned_off',
                    dict(entry, synthetic=dict(ladder_settings, type='ladder')),
                    falling,
                    accepted,
                    book_every_order=True,
                )
            )
        finally:
            api_configuration['order_hold_limits'] = original_hold_limits
        return results

    def run_plan_hold_limits_checks(self):
        """Runs plans asked to hold their orders in the virtual order book, by the request or by one order, and the orders the rule leaves alone or refuses.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(999.95, 1000.00)
        plain = {
            'order': {},
        }
        follow_on = {
            'then': {
                'first': {
                    'order': {},
                },
                'each_fill': {
                    'order': {
                        'side': 'sell',
                    },
                },
            },
        }
        grouped = {
            'together': {
                'children': [
                    {
                        'order': {},
                    },
                    {
                        'order': {
                            'transaction_type': 'SELL',
                        },
                    },
                ],
            },
        }
        grouped_and_asked = {
            'together': {
                'children': [
                    {
                        'order': {
                            'hold_limits': True,
                        },
                    },
                ],
            },
        }
        after_a_rise = {
            'order': {
                'trigger': {
                    'price_crosses': {
                        'level': 1005,
                        'direction': 'at_or_above',
                    },
                },
                'hold_limits': True,
            },
        }
        direct_ladder = {
            'order': {
                'execution': [
                    {
                        'ladder': {
                            'from_price': 1000,
                            'to_price': 995,
                            'steps': 3,
                        },
                    },
                ],
            },
        }
        rise_then_fall = [
            {'quote': steady, 'at': 0},
            {'quote': self.book_at(1004.95, 1005.00), 'at': 1},
            {'quote': touched, 'at': 2},
        ]
        return [
            self.plan_price_result(
                'a_plan_held_by_the_requests_hold_limits_waits_for_the_offer',
                plain,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                accepted,
                body_overrides=self.held_plan_body(plain, True),
            ),
            self.plan_price_result(
                'a_plan_requests_hold_limits_leaves_a_market_order_alone',
                plain,
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides=dict(
                    self.held_plan_body(plain, True),
                    order_type='MARKET',
                    price=None,
                ),
            ),
            self.plan_price_result(
                'a_plan_order_asking_to_hold_a_market_order_is_refused',
                {
                    'order': {
                        'hold_limits': True,
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides={
                    'order_type': 'MARKET',
                    'price': None,
                },
            ),
            self.plan_price_result(
                'a_plan_requests_hold_limits_holds_the_entry_but_not_its_follow_on_order',
                follow_on,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 2, 'updates': [self.update('26091500000021', 'COMPLETE', 10)]},
                ],
                accepted,
                body_overrides=self.held_plan_body(follow_on, True),
            ),
            self.plan_price_result(
                'a_plan_requests_hold_limits_sends_a_margin_checked_group_at_once',
                grouped,
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides=self.held_plan_body(grouped, True),
            ),
            self.plan_price_result(
                'a_plan_order_asking_to_hold_inside_a_margin_checked_group_is_refused',
                grouped_and_asked,
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_order_held_after_its_trigger_is_sent_once_the_offer_comes_even_after_the_trigger_stops_holding',
                after_a_rise,
                rise_then_fall,
                accepted,
            ),
            self.plan_price_result(
                'a_plan_order_held_after_its_trigger_remembers_the_trigger_across_a_restart',
                after_a_rise,
                rise_then_fall,
                accepted,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_order_with_a_ladder_execution_of_its_own_is_held_rung_by_rung',
                direct_ladder,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': self.book_at(997.45, 997.50), 'at': 2},
                ],
                accepted,
                body_overrides=dict(self.held_plan_body(direct_ladder, True), quantity=9),
            ),
            self.plan_price_result(
                'a_plan_requests_hold_limits_must_be_true_or_false',
                plain,
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides=self.held_plan_body(plain, 'yes'),
            ),
        ]

    def run_holding_types_checks(self):
        """Runs today's requests for the single-order types that hold by default, routed to plans, each held until the offer reaches its limit, and the variants that are left to rest.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(999.95, 1000.00)
        below_trigger = self.book_at(994.90, 994.95)
        at_the_limit = self.book_at(989.95, 990.00)
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        funds_low = {
            'summary': {
                'available_balance': 40000.0,
            },
            'pnl': {
                'realized': 0.0,
                'unrealized': 0.0,
            },
        }
        funds_high = {
            'summary': {
                'available_balance': 60000.0,
            },
            'pnl': {
                'realized': 0.0,
                'unrealized': 0.0,
            },
        }
        original_hold_limits = api_configuration['order_hold_limits']
        api_configuration['order_hold_limits'] = True
        try:
            return [
                self.price_result(
                    'a_routed_scheduled_order_is_held_from_its_time_until_the_offer_reaches_it',
                    dict(entry, synthetic={'type': 'scheduled', 'at_time': '10:00:30'}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': steady, 'at': 40},
                        {'quote': touched, 'at': 50},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_good_till_time_order_is_held_until_the_offer_reaches_it',
                    dict(entry, synthetic={'type': 'good_till_time', 'until_time': '14:30'}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_good_till_time_order_made_marketable_at_its_time_rests_at_once',
                    dict(entry, synthetic={'type': 'good_till_time', 'until_time': '14:30', 'at_expiry': 'market'}),
                    [
                        {'quote': steady, 'at': 0},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_time_stop_entry_is_held_until_the_offer_reaches_it',
                    dict(entry, synthetic={'type': 'time_stop', 'minutes': 20}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_account_conditional_order_is_held_after_margin_frees_up_even_if_it_falls_again',
                    dict(entry, synthetic={
                        'type': 'account_conditional',
                        'account_field': 'available_balance',
                        'account_level': 50000,
                        'trigger_direction': 'at_or_above',
                    }),
                    [
                        {'quote': steady, 'at': 0, 'funds': funds_low},
                        {'quote': steady, 'at': 1, 'funds': funds_high},
                        {'quote': touched, 'at': 2, 'funds': funds_low},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_account_conditional_cancel_rests_at_once_since_its_lifetime_only_bounds_a_working_order',
                    dict(entry, synthetic={
                        'type': 'account_conditional',
                        'account_field': 'day_pnl',
                        'account_level': -5000,
                        'trigger_direction': 'at_or_below',
                        'action': 'cancel',
                    }),
                    [
                        {'quote': steady, 'at': 0, 'funds': funds_high},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_limit_if_touched_order_is_held_after_the_touch_until_the_offer_reaches_its_limit',
                    dict(entry, synthetic={'type': 'limit_if_touched', 'trigger_price': 995, 'limit_price': 990}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': below_trigger, 'at': 1},
                        {'quote': below_trigger, 'at': 2},
                        {'quote': at_the_limit, 'at': 3},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_limit_if_touched_order_changed_while_held_is_sent_at_its_new_price',
                    dict(entry, synthetic={'type': 'limit_if_touched', 'trigger_price': 995, 'limit_price': 990}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': below_trigger, 'at': 1},
                        {'quote': below_trigger, 'at': 2},
                        {
                            'quote': self.book_at(991.95, 992.00),
                            'at': 3,
                            'held_change': {
                                'price': '992',
                            },
                        },
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_indicator_triggered_order_is_held_after_its_field_crosses',
                    dict(entry, synthetic={
                        'type': 'indicator_triggered',
                        'watch_field': 'average_price',
                        'trigger_price': 999,
                        'limit_price': 995,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': self.book_at(1000.00, 1000.05) | {'average_price': 998.50}, 'at': 1},
                        {'quote': self.book_at(994.95, 995.00) | {'average_price': 999.50}, 'at': 2},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_cross_instrument_order_is_held_after_the_watched_instrument_fires',
                    dict(entry, synthetic={
                        'type': 'cross_instrument',
                        'watch_instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                        'trigger_price': 995,
                        'limit_price': 990,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': below_trigger, 'at': 1},
                        {'quote': at_the_limit, 'at': 2},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_twap_holds_each_slice_from_its_turn_until_the_offer_reaches_it',
                    dict(entry, synthetic={'type': 'twap', 'slices': 2, 'over_minutes': 1}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                        {'quote': steady, 'at': 31},
                        {'quote': touched, 'at': 40},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_implementation_shortfall_holds_each_slice_from_its_turn',
                    dict(entry, synthetic={'type': 'implementation_shortfall', 'slices': 2, 'over_minutes': 1, 'urgency': 0.5}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': steady, 'at': 31},
                        {'quote': touched, 'at': 40},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_freeze_slicer_holds_the_whole_order_until_the_offer_reaches_it',
                    dict(entry, synthetic={'type': 'freeze_slicer'}),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                    ],
                    accepted,
                ),
                self.price_result(
                    'a_routed_gtt_order_is_held_after_its_touch_until_the_offer_reaches_its_limit',
                    dict(entry, synthetic={
                        'type': 'gtt',
                        'trigger_price': 995,
                        'limit_price': 990,
                        'valid_days': 30,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': below_trigger, 'at': 1},
                        {'quote': at_the_limit, 'at': 2},
                    ],
                    accepted,
                    restart_between_ticks=True,
                ),
            ]
        finally:
            api_configuration['order_hold_limits'] = original_hold_limits

    def run_holding_joins_checks(self):
        """Runs today's requests for the joined types whose entry is held by default, routed to plans, with their exits resting at the broker as the entry fills, and a target held only because its own order asks.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        numbered = dict(accepted, number_orders=True)
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(999.95, 1000.00)
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        released_then_filled = [
            {'quote': steady, 'at': 0},
            {'quote': touched, 'at': 1},
            {'quote': touched, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
        ]
        target_held = {
            'then': {
                'first': {
                    'order': {},
                },
                'each_fill': {
                    'either': {
                        'children': [
                            {
                                'order': {
                                    'side': 'protect',
                                    'pricing': [
                                        {
                                            'native_stop': {
                                                'trigger_price': 990,
                                                'limit_price': 988,
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                'order': {
                                    'side': 'protect',
                                    'pricing': [
                                        {
                                            'fixed': {
                                                'price': 1010,
                                            },
                                        },
                                    ],
                                    'hold_limits': True,
                                },
                            },
                        ],
                        'sibling_rule': 'reduce',
                    },
                },
            },
        }
        legged = {
            'order': {
                'presets': [
                    {
                        'legged_spread': {
                            'net_price': 20,
                            'candidates': [
                                {
                                    'instrument_id': identifiers['reliance'],
                                    'transaction_type': 'BUY',
                                    'quantity': 10,
                                    'price': 1000,
                                },
                                {
                                    'instrument_id': identifiers['reliance_future'],
                                    'transaction_type': 'SELL',
                                    'quantity': 10,
                                },
                            ],
                        },
                    },
                ],
            },
        }
        original_hold_limits = api_configuration['order_hold_limits']
        api_configuration['order_hold_limits'] = True
        try:
            return [
                self.price_result(
                    'a_routed_bracket_holds_its_entry_and_rests_its_exits_once_it_fills',
                    dict(entry, synthetic={'type': 'bracket', 'stop_price': 990, 'stop_limit_price': 988, 'target_price': 1010}),
                    released_then_filled,
                    numbered,
                    book_every_order=True,
                ),
                self.price_result(
                    'a_routed_cover_holds_its_entry_and_rests_its_stop_once_it_fills',
                    dict(entry, synthetic={'type': 'cover', 'stop_price': 990, 'stop_limit_price': 988}),
                    released_then_filled,
                    numbered,
                    book_every_order=True,
                ),
                self.price_result(
                    'a_routed_scale_out_holds_its_entry_and_rests_its_exits_once_it_fills',
                    dict(entry, synthetic={'type': 'scale_out', 'stop_price': 990, 'stop_limit_price': 988, 'target_prices': [1010, 1020]}),
                    released_then_filled,
                    numbered,
                    book_every_order=True,
                ),
                self.price_result(
                    'a_routed_oto_holds_its_first_order_and_sends_its_second_once_it_fills',
                    dict(entry, synthetic={'type': 'oto', 'then': {'transaction_type': 'sell', 'price': 1010}}),
                    released_then_filled,
                    numbered,
                    book_every_order=True,
                ),
                self.price_result(
                    'a_routed_oca_holds_every_candidate_and_ends_the_others_without_a_message',
                    dict(entry, synthetic={
                        'type': 'oca',
                        'candidates': [
                            {
                                'instrument_id': identifiers['reliance'],
                                'quantity': 10,
                                'price': 1000,
                            },
                            {
                                'instrument_id': identifiers['kwil'],
                                'quantity': 10,
                                'price': 250,
                            },
                        ],
                    }),
                    released_then_filled,
                    numbered,
                    book_every_order=True,
                ),
                self.plan_price_result(
                    'a_plan_target_is_held_only_because_its_own_order_asks',
                    target_held,
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                        {'quote': self.book_at(1010.00, 1010.05), 'at': 2},
                    ],
                    numbered,
                ),
                self.price_result(
                    'a_routed_scale_with_profit_taker_holds_each_rung_and_holds_it_again_after_its_profit',
                    dict(entry, quantity=9, synthetic={
                        'type': 'scale_with_profit_taker',
                        'from_price': 1000,
                        'to_price': 990,
                        'steps': 3,
                        'profit_points': 4,
                    }),
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                        {'quote': touched, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 3)]},
                        {'quote': self.book_at(1003.95, 1004.00), 'at': 3, 'updates': [self.update('26091500000102', 'COMPLETE', 3)]},
                        {'quote': touched, 'at': 4},
                    ],
                    numbered,
                    book_every_order=True,
                ),
                self.plan_price_result(
                    'a_plan_scale_with_profit_taker_records_what_a_resting_rung_would_have_filled',
                    {
                        'order': {
                            'presets': [
                                {
                                    'scale_with_profit_taker': {
                                        'from_price': 1000,
                                        'to_price': 990,
                                        'steps': 3,
                                        'profit_points': 4,
                                    },
                                },
                            ],
                            'hold_limits': True,
                        },
                    },
                    [
                        {'quote': steady, 'at': 0, 'estimate': {'queue_filled': 2, 'filled': 2}},
                        {'quote': touched, 'at': 1},
                    ],
                    numbered,
                    body_overrides={
                        'quantity': 9,
                    },
                ),
                self.plan_price_result(
                    'a_plan_grid_asked_to_hold_by_its_own_order_is_refused',
                    {
                        'order': {
                            'presets': [
                                {
                                    'grid': {
                                        'levels': 2,
                                        'step_points': 5,
                                        'most_inventory': 20,
                                    },
                                },
                            ],
                            'hold_limits': True,
                        },
                    },
                    [
                        {'quote': steady, 'at': 0},
                    ],
                    numbered,
                ),
                self.plan_price_result(
                    'a_plan_that_says_nothing_is_held_while_holding_is_on',
                    {
                        'order': {},
                    },
                    [
                        {'quote': steady, 'at': 0},
                        {'quote': touched, 'at': 1},
                    ],
                    numbered,
                ),
                self.plan_price_result(
                    'a_plan_legged_spread_works_its_first_leg_at_the_broker_even_when_the_request_holds',
                    legged,
                    [
                        {'quote': steady, 'at': 0},
                    ],
                    numbered,
                    body_overrides=self.held_plan_body(legged, True),
                ),
            ]
        finally:
            api_configuration['order_hold_limits'] = original_hold_limits

    def held_plan_body(self, plan, hold_limits):
        """Body fields giving a plan order a request-level `hold_limits`.

        Args:
            plan (dict): The `plan` object.
            hold_limits (object): The request's `hold_limits`.

        Returns:
            dict: The `synthetic` body field, to lay over the body.
        """
        return {
            'synthetic': {
                'type': 'plan',
                'plan': plan,
                'hold_limits': hold_limits,
            },
        }

    def run_plan_kept_whole_checks(self):
        """Runs plan orders kept whole, such as a grid, beside today's checks of the same types.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        refused = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_refusal('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)

        def grid(settings):
            """A plan of one grid.

            Args:
                settings (dict): The grid's settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'grid': settings,
                        },
                    ],
                },
            }

        numbered = dict(accepted, number_orders=True)

        def quote(settings):
            """A plan of one two-sided quote.

            Args:
                settings (dict): The quote's settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'two_sided_quote': settings,
                        },
                    ],
                },
            }

        def scale(settings):
            """A plan of one scale with profit-taker.

            Args:
                settings (dict): Its settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'scale_with_profit_taker': settings,
                        },
                    ],
                },
            }

        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS

        def hedge(settings):
            """A plan of one exposure hedge.

            Args:
                settings (dict): Its settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'exposure_hedge': settings,
                        },
                    ],
                },
            }

        stop_in_the_book = {
            'order_type': 'SL',
            'trigger_price': 990,
        }
        two_targets = {
            'stop_price': 990,
            'stop_limit_price': 988,
            'target_prices': [
                1010,
                1020,
            ],
        }

        def scale_out(settings):
            """A plan of one order with the scale-out preset.

            Args:
                settings (dict): Its settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'scale_out': settings,
                        },
                    ],
                },
            }

        condor_legs = [
            {
                'instrument_id': identifiers['reliance'],
                'quantity': 10,
                'price': 1000,
            },
            {
                'instrument_id': identifiers['kwil'],
                'transaction_type': 'SELL',
                'quantity': 10,
                'price': 250,
            },
        ]

        def strategy(settings):
            """A plan of one order with the strategy stop preset.

            Args:
                settings (dict): Its settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            'strategy_stop': settings,
                        },
                    ],
                },
            }

        capped_at_twenty = {
            'levels': 2,
            'step_points': 5,
            'most_inventory': 20,
        }
        return [
            self.plan_result(
                'a_plan_grid_replaces_a_filled_rung_with_its_opposite',
                grid(capped_at_twenty),
                [
                    self.update('26091500000021', 'COMPLETE', 5),
                ],
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                },
            ),
            self.plan_result(
                'a_plan_grid_stops_adding_to_a_side_once_it_hits_its_cap',
                grid({
                    'levels': 2,
                    'step_points': 5,
                    'most_inventory': 5,
                }),
                [
                    self.update('26091500000021', 'COMPLETE', 5),
                ],
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                },
            ),
            self.plan_result(
                'a_plan_grid_without_an_inventory_cap_is_refused',
                grid({
                    'levels': 2,
                    'step_points': 5,
                }),
                [],
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                },
            ),
            self.plan_price_result(
                'a_plan_grid_with_one_rung_refused_answers_partial_with_207',
                grid({
                    'levels': 1,
                    'step_points': 5,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                {
                    'sequence': [
                        accepted,
                        refused,
                    ],
                },
            ),
            self.plan_price_result(
                'a_plan_grid_with_every_rung_refused_answers_rejected',
                grid({
                    'levels': 1,
                    'step_points': 5,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                refused,
            ),
            self.plan_price_result(
                'a_plan_grid_answers_a_fill_once_across_a_restart',
                grid(capped_at_twenty),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000021', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 2},
                ],
                accepted,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_two_sided_quote_follows_the_mid',
                quote({
                    'half_spread_points': 1,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 1},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_filled_bid_skews_the_ask_and_stops_buying_at_the_cap',
                quote({
                    'half_spread_points': 1,
                    'skew_ticks': 2,
                    'most_inventory': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10),
                        ],
                    },
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_two_sided_quote_without_a_spread_is_refused',
                quote({
                    'most_inventory': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_two_sided_quote_stops_when_its_join_cancels_it',
                {
                    'either': {
                        'sibling_rule': 'cancel',
                        'children': [
                            quote({
                                'half_spread_points': 1,
                                'most_inventory': 30,
                            }),
                            {
                                'order': {
                                    'presets': [
                                        {
                                            'market_if_touched': {
                                                'trigger_price': 995,
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {
                        'quote': self.book_at(994.90, 994.95),
                        'at': 2,
                        'updates': [
                            self.update('26091500000103', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': self.book_at(994.90, 994.95),
                        'at': 3,
                        'updates': [
                            self.update('26091500000101', 'CANCELLED', 0),
                            self.update('26091500000102', 'CANCELLED', 0),
                        ],
                    },
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_scale_with_profit_taker_takes_each_rungs_profit_and_places_it_again',
                scale({
                    'from_price': 1000,
                    'to_price': 990,
                    'steps': 3,
                    'profit_points': 4,
                    'most_cycles': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000102', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000104', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'updates': [
                            self.update('26091500000105', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 4,
                        'updates': [
                            self.update('26091500000106', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 5,
                        'updates': [
                            self.update('26091500000107', 'COMPLETE', 10),
                        ],
                    },
                ],
                numbered,
                body_overrides={
                    'quantity': 30,
                },
            ),
            self.plan_price_result(
                'a_plan_scale_with_profit_taker_without_a_profit_distance_is_refused',
                scale({
                    'from_price': 1000,
                    'to_price': 990,
                    'steps': 3,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides={
                    'quantity': 30,
                },
            ),
            self.plan_price_result(
                'a_plan_scale_with_profit_taker_is_done_once_its_last_cycle_is_taken',
                scale({
                    'from_price': 1000,
                    'to_price': 995,
                    'steps': 2,
                    'profit_points': 4,
                    'most_cycles': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000102', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'updates': [
                            self.update('26091500000103', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 4,
                        'updates': [
                            self.update('26091500000104', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 5,
                        'updates': [
                            self.update('26091500000105', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 6,
                        'updates': [
                            self.update('26091500000106', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 7,
                        'updates': [
                            self.update('26091500000107', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 8,
                        'updates': [
                            self.update('26091500000108', 'COMPLETE', 10),
                        ],
                    },
                ],
                numbered,
                body_overrides={
                    'quantity': 20,
                },
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_exposure_hedge_trades_when_the_band_is_left',
                hedge({
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance'],
                    'hedge_exposure_per_unit': 1,
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=100,
            ),
            self.plan_price_result(
                'a_plan_exposure_hedge_prices_a_hedge_in_another_instrument_from_that_instruments_quote',
                hedge({
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance_future'],
                    'hedge_exposure_per_unit': 0.2,
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.book_at(1004.10, 1004.30),
                        },
                    },
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=100,
            ),
            self.plan_price_result(
                'a_plan_exposure_hedge_inside_its_band_does_nothing',
                hedge({
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance'],
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=5,
            ),
            self.plan_price_result(
                'a_plan_exposure_hedge_keeps_watching_after_its_hedge_fills',
                hedge({
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance'],
                    'hedge_exposure_per_unit': 1,
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 100),
                        ],
                    },
                    {'quote': steady, 'at': 2},
                ],
                accepted,
                positions=100,
                restart_between_ticks=True,
            ),
            self.plan_result(
                'a_plan_scale_out_arms_one_stop_and_several_targets',
                scale_out({
                    'stop_price': 990,
                    'stop_limit_price': 988,
                    'target_prices': [
                        1010,
                        1020,
                        1030,
                    ],
                }),
                [
                    self.update('26091500000021', 'COMPLETE', 9),
                ],
                accepted,
                body_overrides={
                    'quantity': 9,
                },
            ),
            self.plan_result(
                'a_plan_scale_out_takes_only_the_new_part_of_a_targets_second_fill_off_the_stop',
                scale_out(two_targets),
                [
                    self.update('26091500000101', 'COMPLETE', 10),
                    self.update('26091500000102', 'OPEN', 0),
                    self.update('26091500000103', 'OPEN', 2),
                    self.update('26091500000103', 'OPEN', 4),
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_scale_out_moves_its_stop_to_the_entry_price_after_a_target',
                scale_out(two_targets),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10, average_price=1000.0),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000102', 'OPEN', 0, order_type='SL'),
                            self.update('26091500000103', 'OPEN', 0),
                            self.update('26091500000104', 'OPEN', 0),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'updates': [
                            self.update('26091500000103', 'COMPLETE', 5),
                        ],
                    },
                ],
                numbered,
                book_overrides=stop_in_the_book,
            ),
            self.plan_result(
                'a_plan_scale_out_stop_filling_cancels_the_targets',
                scale_out(two_targets),
                [
                    self.update('26091500000101', 'COMPLETE', 10),
                    self.update('26091500000102', 'OPEN', 0),
                    self.update('26091500000103', 'OPEN', 0),
                    self.update('26091500000104', 'OPEN', 0),
                    self.update('26091500000102', 'COMPLETE', 10),
                    self.update('26091500000103', 'CANCELLED', 0),
                    self.update('26091500000104', 'CANCELLED', 0),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_scale_out_exits_alone_are_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'scale_out_exits': two_targets,
                            },
                        ],
                    },
                },
                [],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_scale_out_after_a_market_if_touched_entry',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                            {
                                'scale_out': two_targets,
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {
                        'quote': self.book_at(994.90, 994.95),
                        'at': 2,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10),
                        ],
                    },
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_strategy_stop_closes_every_leg_when_the_total_is_past_its_limit',
                strategy({
                    'loss_limit': -500,
                    'candidates': condor_legs,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 10, average_price=1000.0),
                        ],
                    },
                    {'quote': self.book_at(900.00, 900.05), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_strategy_stop_leaves_a_strategy_inside_its_limits_alone',
                strategy({
                    'loss_limit': -500,
                    'candidates': condor_legs,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 10, average_price=1000.0),
                        ],
                    },
                    {'quote': self.book_at(990.00, 990.05), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_strategy_stop_takes_its_profit_closing_the_short_first',
                strategy({
                    'profit_target': 500,
                    'candidates': condor_legs,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10, average_price=1000.0),
                            self.update('26091500000102', 'COMPLETE', 10, average_price=250.0),
                        ],
                        'other_quotes': {
                            'kwil': self.book_at(250.00, 250.05),
                        },
                    },
                    {
                        'quote': self.book_at(1100.00, 1100.05),
                        'at': 1,
                        'other_quotes': {
                            'kwil': self.book_at(250.00, 250.05),
                        },
                    },
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_strategy_stop_exits_alone_are_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'strategy_stop_exits': {
                                    'loss_limit': -500,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_repeat_stops_sending_copies_once_until_holds',
                {
                    'repeat': {
                        'child': {
                            'order': {},
                        },
                        'times': 3,
                        'every_minutes': 1,
                        'until': {
                            'price_crosses': {
                                'level': 1010,
                                'direction': 'at_or_above',
                            },
                        },
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 30},
                    {'quote': steady, 'at': 61},
                    {'quote': steady, 'at': 121},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_grid_beside_another_preset_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'grid': capped_at_twenty,
                            },
                            {
                                'post_only': {},
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
        ]

    def run_plan_virtual_limit_checks(self):
        """Runs plan orders held in the engine until their limit is marketable, sent or filled on paper, beside today's virtual limit checks.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        virtual_limit = {
            'order': {
                'presets': [
                    {
                        'virtual_limit': {},
                    },
                ],
            },
        }
        paper = {
            'order': {
                'presets': [
                    {
                        'virtual_limit': {
                            'paper': True,
                        },
                    },
                ],
            },
        }
        return [
            self.plan_price_result(
                'a_plan_virtual_limit_is_held_until_the_offer_reaches_its_price',
                virtual_limit,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(999.50, 999.55), 'at': 1},
                    {
                        'quote': self.book_at(999.40, 999.45),
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 2,
                    },
                    {'quote': self.book_at(999.40, 999.45), 'at': 3},
                ],
                accepted,
                body_overrides={
                    'price': 999.50,
                },
            ),
            self.plan_price_result(
                'a_plan_virtual_limit_ignores_a_stale_quote',
                virtual_limit,
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': dict(self.book_at(999.40, 999.45), stale=True),
                        'at': 1,
                    },
                    {'quote': self.book_at(999.40, 999.45), 'at': 2},
                ],
                accepted,
                body_overrides={
                    'price': 999.50,
                },
            ),
            self.plan_price_result(
                'a_plan_virtual_limit_must_be_a_limit_order',
                virtual_limit,
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                body_overrides={
                    'order_type': 'MARKET',
                    'price': None,
                },
            ),
            self.plan_price_result(
                'a_plan_paper_virtual_limit_fills_from_the_queue_estimate',
                paper,
                [
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 0,
                            'filled': 0,
                        },
                        'at': 0,
                    },
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 1,
                    },
                    {
                        'quote': self.book_at(999.40, 999.45),
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 10,
                        },
                        'at': 2,
                    },
                ],
                accepted,
                body_overrides={
                    'price': 999.50,
                },
            ),
            self.plan_price_result(
                'a_plan_paper_fill_is_not_repeated_after_a_restart',
                paper,
                [
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 0,
                    },
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                restart_between_ticks=True,
                body_overrides={
                    'price': 999.50,
                },
            ),
            self.plan_price_result(
                'a_plan_held_limit_changed_while_held_fires_at_its_new_price_and_quantity',
                virtual_limit,
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'held_change': {
                            'price': '1000.05',
                            'quantity': 20,
                        },
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'held_change': {
                            'price': '999',
                        },
                    },
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_paper_order_cannot_be_cut_below_what_it_filled',
                paper,
                [
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 0,
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'held_change': {
                            'quantity': 4,
                        },
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'held_change': {
                            'price': '999.53',
                        },
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'held_change': {
                            'quantity': 20,
                        },
                    },
                ],
                accepted,
                body_overrides={
                    'price': 999.50,
                },
            ),
            self.plan_price_result(
                'a_plan_paper_order_must_wait_on_limit_marketable',
                {
                    'order': {
                        'trigger': {
                            'price_crosses': {
                                'level': 995,
                            },
                        },
                        'venue': [
                            {
                                'session': 'paper',
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_paper_order_cannot_be_joined',
                {
                    'then': {
                        'first': {
                            'order': {
                                'presets': [
                                    {
                                        'virtual_limit': {
                                            'paper': True,
                                        },
                                    },
                                ],
                            },
                        },
                        'on_complete': {
                            'order': {
                                'side': 'protect',
                            },
                        },
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
        ]

    def run_plan_trigger_checks(self):
        """Runs plan orders that wait for a trigger, protect a position or are priced by a pricing rule, through price ticks.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(994.90, 994.95)
        return [
            self.plan_price_result(
                'a_plan_market_if_touched_waits_then_takes_the_offer',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_waiting_plan_survives_a_restart_and_fires_once',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_buy_sent_in_lower_case_still_waits_for_the_dip',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
                transaction_type='buy',
            ),
            self.plan_price_result(
                'a_plan_hidden_stop_for_a_long_sent_in_lower_case_sells',
                {
                    'order': {
                        'presets': [
                            {
                                'hidden_stop': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                accepted,
                positions=10,
                transaction_type='buy',
            ),
            self.plan_price_result(
                'a_plan_limit_if_touched_rests_its_limit_once_touched',
                {
                    'order': {
                        'presets': [
                            {
                                'limit_if_touched': {
                                    'trigger_price': 995,
                                    'limit_price': 996,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_scheduled_order_waits_for_its_time',
                {
                    'order': {
                        'presets': [
                            {
                                'scheduled': {
                                    'at_time': '10:00:30',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 10},
                    {'quote': steady, 'at': 40},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_joins_a_time_and_a_price_trigger_so_both_must_hold',
                {
                    'order': {
                        'presets': [
                            {
                                'scheduled': {
                                    'at_time': '10:00:30',
                                },
                            },
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 10},
                    {'quote': steady, 'at': 40},
                    {'quote': touched, 'at': 50},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_held_trigger_waits_until_the_level_has_held',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                    'trigger_on': 'held',
                                    'hold_seconds': 5,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 3},
                    {'quote': touched, 'at': 7},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_cross_instrument_watches_another_instruments_price',
                {
                    'order': {
                        'presets': [
                            {
                                'cross_instrument': {
                                    'watch_instrument_id': identifiers['reliance_future'],
                                    'trigger_price': 1010,
                                    'trigger_direction': 'at_or_above',
                                    'limit_price': 1000,
                                },
                            },
                        ],
                    },
                },
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.book_at(1004.10, 1004.30),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'other_quotes': {
                            'reliance_future': self.book_at(1010.10, 1010.30),
                        },
                    },
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_hidden_stop_protects_a_long_and_sells_past_the_bid',
                {
                    'order': {
                        'presets': [
                            {
                                'hidden_stop': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                accepted,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_that_protects_with_no_position_held_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'hidden_stop': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_with_a_native_stop_rests_it_at_once',
                {
                    'order': {
                        'side': 'protect',
                        'pricing': [
                            {
                                'native_stop': {
                                    'trigger_price': 990,
                                    'limit_price': 988,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_later_pricing_replaces_a_presets_with_a_warning',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                        'pricing': [
                            {
                                'fixed': {
                                    'price': 994,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_with_two_sides_and_bad_trigger_settings_lists_them_all',
                {
                    'order': {
                        'presets': [
                            {
                                'hidden_stop': {
                                    'trigger_price': -5,
                                },
                            },
                        ],
                        'side': 'buy',
                        'trigger': {
                            'all': [
                                {
                                    'time_after': 1000,
                                },
                                {
                                    'price_crosses': {
                                        'level': 990,
                                        'confirm': 'held',
                                    },
                                },
                            ],
                        },
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
        ]

    def run_plan_join_checks(self):
        """Runs plans that join orders with Then and Either, through fills and price ticks.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(994.90, 994.95)
        bracket = {
            'bracket': {
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_price': 1010,
            },
        }
        oco = {
            'oco': {
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_price': 1010,
            },
        }
        hidden_with_backstop = {
            'hidden_stop': {
                'trigger_price': 995,
                'backstop_price': 980,
                'backstop_limit_price': 978,
            },
        }
        return [
            self.plan_price_result(
                'a_plan_bracket_grows_its_exits_and_takes_only_new_fills_off_the_stop',
                {
                    'order': {
                        'presets': [
                            bracket,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 4)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000103', 'OPEN', 3)]},
                    {'quote': steady, 'at': 4, 'updates': [self.update('26091500000103', 'OPEN', 7)]},
                    {'quote': steady, 'at': 5, 'updates': [self.update('26091500000103', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 6, 'updates': [self.update('26091500000102', 'CANCELLED', 0)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_bracket_behaves_the_same_with_a_restart_between_fills',
                {
                    'order': {
                        'presets': [
                            bracket,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 4)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000103', 'OPEN', 3)]},
                    {'quote': steady, 'at': 4, 'updates': [self.update('26091500000103', 'OPEN', 7)]},
                    {'quote': steady, 'at': 5, 'updates': [self.update('26091500000103', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 6, 'updates': [self.update('26091500000102', 'CANCELLED', 0)]},
                ],
                numbered,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_bracket_exit_filling_cancels_the_rest_of_the_entry',
                {
                    'order': {
                        'presets': [
                            bracket,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 4)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000103', 'OPEN', 2)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_oco_protects_a_held_position_and_reduces_the_sibling',
                {
                    'order': {
                        'presets': [
                            oco,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000102', 'OPEN', 3)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'OPEN', 7)]},
                ],
                numbered,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_oco_with_nothing_held_is_refused',
                {
                    'order': {
                        'presets': [
                            oco,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_cover_places_its_stop_once_the_entry_fills',
                {
                    'order': {
                        'presets': [
                            {
                                'cover': {
                                    'stop_price': 990,
                                    'stop_limit_price': 988,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_oto_places_its_then_order_sized_to_the_fill',
                {
                    'order': {
                        'presets': [
                            {
                                'oto': {
                                    'then': {
                                        'transaction_type': 'SELL',
                                        'price': 1010,
                                    },
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 6)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_hidden_stop_cancels_its_backstop_before_it_exits',
                {
                    'order': {
                        'presets': [
                            hidden_with_backstop,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                ],
                numbered,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_hidden_stop_whose_backstop_fills_stops_watching',
                {
                    'order': {
                        'presets': [
                            hidden_with_backstop,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': touched, 'at': 2},
                ],
                numbered,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_market_if_touched_entry_with_a_bracket_around_it',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                            bracket,
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_reduce_join_over_a_join_and_two_join_presets_are_refused',
                {
                    'either': {
                        'sibling_rule': 'reduce',
                        'children': [
                            {
                                'order': {
                                    'presets': [
                                        bracket,
                                        oco,
                                    ],
                                },
                            },
                            {
                                'then': {
                                    'first': {
                                        'order': {},
                                    },
                                    'each_fill': {
                                        'order': {},
                                    },
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
        ]

    def run_plan_trailing_checks(self):
        """Runs plans whose orders trail the market, as a native stop that moves or as an engine-side trigger.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        stop_in_the_book = {
            'order_type': 'SL',
            'trigger_price': 995.05,
        }
        trail_five = {
            'trail_points': 5,
            'stop_limit_offset': 1,
        }
        return [
            self.plan_price_result(
                'a_plan_trailing_stop_follows_a_rising_market_and_never_back',
                {
                    'order': {
                        'presets': [
                            {
                                'trailing_stop': trail_five,
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(1002.95, 1003.00), 'at': 1},
                    {'quote': self.book_at(1000.95, 1001.00), 'at': 2},
                    {'quote': self.book_at(1005.95, 1006.00), 'at': 3},
                ],
                numbered,
                positions=10,
                book_overrides=stop_in_the_book,
            ),
            self.plan_price_result(
                'a_plan_trailing_entry_follows_a_falling_market_down',
                {
                    'order': {
                        'presets': [
                            {
                                'trailing_entry': trail_five,
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(996.95, 997.00), 'at': 1},
                    {'quote': self.book_at(998.95, 999.00), 'at': 2},
                ],
                numbered,
                book_overrides=stop_in_the_book,
            ),
            self.plan_price_result(
                'a_plan_trailing_stop_waits_for_its_activation_level',
                {
                    'order': {
                        'presets': [
                            {
                                'trailing_stop': dict(trail_five, activate_at=1010),
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(1005.00, 1005.05), 'at': 1},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 2},
                    {'quote': self.book_at(1012.00, 1012.05), 'at': 3},
                ],
                numbered,
                positions=10,
                book_overrides=stop_in_the_book,
            ),
            self.plan_price_result(
                'a_plan_engine_side_trailing_exit_sells_past_the_bid_on_the_pullback',
                {
                    'order': {
                        'side': 'protect',
                        'trigger': {
                            'trails': {
                                'points': 5,
                            },
                        },
                        'pricing': [
                            {
                                'marketable': {
                                    'buffer_ticks': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(1005.95, 1006.00), 'at': 1},
                    {'quote': self.book_at(1002.95, 1003.00), 'at': 2},
                    {'quote': self.book_at(1000.90, 1000.95), 'at': 3},
                ],
                numbered,
                positions=10,
                book_overrides=stop_in_the_book,
            ),
            self.plan_price_result(
                'a_plan_entry_then_a_trailing_stop_sized_to_its_fill',
                {
                    'then': {
                        'first': {
                            'order': {},
                        },
                        'each_fill': {
                            'order': {
                                'presets': [
                                    {
                                        'trailing_stop': trail_five,
                                    },
                                ],
                            },
                        },
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': self.book_at(1003.95, 1004.00), 'at': 2},
                ],
                numbered,
                book_overrides=stop_in_the_book,
            ),
        ]

    def run_stale_quote_checks(self):
        """Runs triggers on quotes marked stale, which the quote combiner marks when a quote's broker has gone silent with no healthy backup.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(994.90, 994.95)
        stale_touched = dict(touched, stale=True)
        return [
            self.price_result(
                'a_market_if_touched_order_is_not_fired_by_a_stale_quote',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': stale_touched, 'at': 1},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_limit_if_touched_order_is_not_fired_by_a_stale_quote',
                dict(entry, hold_limits=False, synthetic={
                    'type': 'limit_if_touched',
                    'trigger_price': 995,
                    'limit_price': 990,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': stale_touched, 'at': 1},
                    {'quote': steady, 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_double_last_trigger_does_not_count_a_stale_quote',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                    'trigger_on': 'double_last',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': stale_touched, 'at': 2},
                    {'quote': touched, 'at': 3},
                ],
                accepted,
            ),
            self.price_result(
                'a_post_only_order_waits_for_a_fresh_book_instead_of_judging_a_stale_one',
                dict(entry, price=1000.10, synthetic={
                    'type': 'post_only',
                    'on_crossing': 'refuse',
                }),
                [
                    {'quote': dict(steady, stale=True), 'at': 0},
                    {'quote': self.book_at(1000.10, 1000.15), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_peg_does_not_follow_a_stale_quote',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': dict(self.book_at(1000.40, 1000.45), stale=True), 'at': 2},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 4},
                ],
                accepted,
            ),
            self.price_result(
                'a_chaser_does_not_cross_to_a_stale_offer',
                dict(entry, synthetic={
                    'type': 'chaser',
                    'cross_after_seconds': 10,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': dict(self.book_at(1000.00, 1005.00), stale=True), 'at': 11},
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 12},
                ],
                accepted,
            ),
            self.price_result(
                'an_underlying_peg_does_not_move_on_a_stale_index',
                dict(entry, synthetic={
                    'type': 'underlying_peg',
                    'watch_instrument_id': identifiers['nifty_index'],
                    'delta': 0.5,
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': dict(self.scenarios.quote(last_price=25040), stale=True)}},
                    {'quote': steady, 'at': 2, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25020)}},
                ],
                accepted,
            ),
            self.price_result(
                'a_trailing_stop_does_not_follow_a_stale_price',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': dict(self.book_at(1040.00, 1040.05), stale=True), 'at': 1},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 2},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_discretionary_order_does_not_take_a_stale_offer',
                dict(entry, synthetic={
                    'type': 'discretionary',
                    'discretion_points': 0.25,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': dict(self.book_at(1000.00, 1000.20), stale=True), 'at': 1},
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_candle_close_stop_leaves_a_stale_quote_out_of_its_bar',
                dict(entry, synthetic={
                    'type': 'candle_close_stop',
                    'trigger_price': 995,
                    'bar_minutes': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': dict(self.book_at(990.00, 990.05), stale=True), 'at': 50},
                    {'quote': steady, 'at': 61},
                ],
                accepted,
                positions=10,
            ),
        ]

    def run_stop_type_checks(self):
        """Runs the stop types where a price off the tick, a shrinking range, a cancel before the first send or a restart used to leave a position unprotected.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        frozen = FROZEN_NOW.timestamp()
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        steady = self.book_at(1000.00, 1000.05)
        low = self.book_at(990.00, 990.05)
        stop_in_the_book = {
            'order_type': 'SL',
            'trigger_price': 990.05,
        }
        calming_path = [
            1000.05,
            1004,
            998,
            1006,
            1010,
            1002,
            1012,
            1008,
            1015,
            1007,
            1018,
            1016,
            1022,
            1014,
            1025,
            1021,
            1026,
            1024,
            1027,
            1026,
            1028,
            1027,
            1029,
            1028,
            1029.5,
            1028.5,
            1030,
            1029.5,
            1030.5,
            1030,
            1031,
            1030.5,
            1024,
            1022,
            1021,
            1020,
        ]
        calming_steps = []
        for index, price in enumerate(calming_path):
            calming_steps.append({
                'quote': self.book_at(round(price - 0.05, 2), price),
                'at': index * 15,
            })
        candle_stop = {
            'type': 'candle_close_stop',
            'trigger_price': 995,
            'bar_minutes': 1,
        }
        return [
            self.clock_result(
                'a_daily_stop_off_the_tick_is_refused_when_placed',
                dict(entry, synthetic={
                    'type': 'daily_stop',
                    'stop_price': 990.03,
                    'stop_limit_price': 988,
                    'arm_at': '09:20',
                }),
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.plan_price_result(
                'a_daily_stop_cancelled_before_its_first_morning_ends_cancelled',
                {
                    'order': {
                        'presets': [
                            {
                                'daily_stop': {
                                    'stop_price': 990,
                                    'stop_limit_price': 988,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': 'root'}},
                    {'quote': steady, 'at': 2},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'an_average_range_trail_never_moves_its_stop_through_the_market',
                dict(entry, synthetic={
                    'type': 'atr_trail',
                    'trail_points': 15,
                    'stop_limit_offset': 2,
                    'bar_minutes': 1,
                    'periods': 3,
                    'atr_multiple': 2,
                }),
                calming_steps,
                accepted,
                book_overrides=stop_in_the_book,
                positions=10,
            ),
            self.price_result(
                'an_average_range_trail_with_more_periods_than_bars_kept_is_refused',
                dict(entry, synthetic={
                    'type': 'atr_trail',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'periods': 50,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'an_average_range_trail_keeps_its_bars_across_a_restart',
                dict(entry, synthetic={
                    'type': 'atr_trail',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'bar_minutes': 1,
                    'periods': 2,
                    'atr_multiple': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1040.00, 1040.05), 'at': 10},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 70},
                    {'quote': self.book_at(1060.00, 1060.05), 'at': 130, 'restart': True},
                    {'quote': self.book_at(1080.00, 1080.05), 'at': 190},
                ],
                accepted,
                book_overrides=stop_in_the_book,
                positions=10,
            ),
            self.price_result(
                'a_candle_close_stop_remembers_which_side_its_bar_is_closing_on_across_a_restart',
                dict(entry, synthetic=candle_stop),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 30},
                    {'quote': low, 'at': 50, 'restart': True},
                    {'quote': steady, 'at': 61},
                ],
                accepted,
                positions=10,
            ),
        ]

    def run_linked_order_checks(self):
        """Runs the linked types where a later fill, a race or a price off the tick used to leave a position unprotected or a parent in the wrong state.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS

        def preset_plan(name, settings):
            """A plan of one order with one preset.

            Args:
                name (str): The preset.
                settings (dict): Its settings.

            Returns:
                dict: The plan.
            """
            return {
                'order': {
                    'presets': [
                        {
                            name: settings,
                        },
                    ],
                },
            }

        bracket = {
            'stop_price': 990,
            'stop_limit_price': 988,
            'target_price': 1010,
        }
        oco = {
            'stop_price': 990,
            'stop_limit_price': 988,
            'target_price': 1010,
        }
        two_targets = {
            'stop_price': 990,
            'stop_limit_price': 988,
            'target_prices': [
                1010,
                1020,
            ],
        }
        breakout = {
            'buy_trigger': 1010,
            'buy_limit': 1012,
            'sell_trigger': 990,
            'sell_limit': 988,
            'stop_distance': 25,
            'stop_limit_offset': 2,
        }
        candidates = {
            'candidates': [
                {
                    'instrument_id': identifiers['reliance'],
                    'quantity': 10,
                    'price': 1000,
                },
                {
                    'instrument_id': identifiers['kwil'],
                    'quantity': 10,
                    'price': 250,
                },
            ],
        }
        return [
            self.plan_price_result(
                'a_bracket_sends_its_exits_again_when_the_entry_fills_after_they_finished',
                preset_plan('bracket', bracket),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 4)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000103', 'COMPLETE', 4)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000102', 'CANCELLED', 0)]},
                    {'quote': steady, 'at': 4, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'an_oto_sends_its_second_order_again_when_the_first_fills_after_it_filled',
                preset_plan('oto', {
                    'then': {
                        'transaction_type': 'SELL',
                        'price': 1010,
                    },
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'OPEN', 6)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'COMPLETE', 6)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_bracket_stop_off_the_tick_is_refused_when_placed',
                preset_plan('bracket', dict(bracket, stop_price=990.03)),
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_scale_out_target_off_the_tick_is_refused_when_placed',
                preset_plan('scale_out', dict(two_targets, target_prices=[1010, 1020.02])),
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_scale_out_moves_its_stop_to_the_entry_price_rounded_to_the_tick',
                preset_plan('scale_out', two_targets),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10, average_price=1000.03),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000102', 'OPEN', 0, order_type='SL'),
                            self.update('26091500000103', 'OPEN', 0),
                            self.update('26091500000104', 'OPEN', 0),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'updates': [
                            self.update('26091500000103', 'COMPLETE', 5),
                        ],
                    },
                ],
                numbered,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990,
                },
            ),
            self.plan_price_result(
                'an_oco_is_sent_to_the_broker_that_holds_the_position',
                preset_plan('oco', oco),
                [
                    {'quote': steady, 'at': 0},
                ],
                dict(
                    self.scenarios.answers.json_answer(
                        200,
                        self.scenarios.answers.place_success('zerodha'),
                    ),
                    number_orders=True,
                ),
                positions={
                    'zerodha': 10,
                },
            ),
            self.plan_price_result(
                'an_oco_on_a_position_held_at_two_brokers_is_refused',
                preset_plan('oco', oco),
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
                positions={
                    'flattrade': 6,
                    'zerodha': 4,
                },
            ),
            self.plan_price_result(
                'an_oco_larger_than_the_position_is_refused',
                preset_plan('oco', oco),
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
                positions=6,
            ),
            self.plan_result(
                'an_oca_keeps_the_candidate_that_filled_first_when_another_fills_before_its_cancel',
                preset_plan('oca', candidates),
                [
                    self.update('26091500000102', 'OPEN', 3),
                    self.update('26091500000101', 'OPEN', 2),
                    self.update('26091500000101', 'CANCELLED', 2),
                ],
                numbered,
            ),
            self.plan_result(
                'an_oca_candidate_refused_after_others_were_placed_leaves_them_watched',
                preset_plan('oca', {
                    'candidates': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'quantity': 10,
                            'price': 1000,
                        },
                        {
                            'instrument_id': identifiers['kwil'],
                            'quantity': 10,
                            'price': 250,
                        },
                        {
                            'instrument_id': identifiers['sensex_option'],
                            'price': 100,
                        },
                    ],
                }),
                [
                    self.update('26091500000101', 'OPEN', 4),
                ],
                numbered,
            ),
            self.plan_result(
                'a_two_sided_breakout_whose_sides_both_fill_cancels_its_exit',
                preset_plan('two_sided_breakout', breakout),
                [
                    self.update('26091500000101', 'OPEN', 10, average_price=1010.0),
                    self.update('26091500000102', 'COMPLETE', 10, average_price=990.0),
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_whose_only_order_is_rejected_after_it_was_accepted_ends_rejected',
                preset_plan('bracket', bracket),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'REJECTED', 0)]},
                ],
                numbered,
            ),
        ]

    def seed_positions(self, quantity, product='MIS'):
        """Seeds a net position in RELIANCE, intraday unless told otherwise, held at Flattrade or split across brokers.

        The unified positions document is what reduce-only orders and quantity references read, and it holds one row for the whole position, as the real document merges a position across brokers. The types that close positions read each broker's own hash instead, and find the instrument from the broker's token in `unified:broker_tokens`, so each broker's share is seeded there too.

        Args:
            quantity (float | dict): The net quantity, signed, held at Flattrade; or broker names to each one's signed quantity.
            product (str): The product each broker holds it on, such as `MIS` or `NRML`.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(quantity, dict):
            held = quantity
        else:
            held = {
                'flattrade': quantity,
            }
        total = 0
        for broker_quantity in held.values():
            total = total + broker_quantity
        self.fake_redis.strings['unified:portfolio:positions'] = json.dumps(
            self.scenarios.positions(total),
        )
        reliance = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']
        broker_tokens = {}
        for broker_name, broker_quantity in held.items():
            self.fake_redis.hashes[f'{broker_name}:portfolio:positions'] = {
                f'NET:NSE:2885:{product}': json.dumps({
                    'position': {
                        'instrument_token': '2885',
                        'tradingsymbol': 'RELIANCE-EQ',
                        'exchange': 'NSE',
                        'product': product,
                        'quantity': broker_quantity,
                        'day_or_net': 'NET',
                    },
                }),
            }
            broker_tokens[f'{broker_name}:2885'] = json.dumps([
                reliance,
            ])
        self.fake_redis.hashes['unified:broker_tokens'] = broker_tokens

    def run_plan_execution_checks(self):
        """Runs plans whose orders are sent as pieces: an iceberg, timed slices, and combinations with triggers and joins.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        return [
            self.plan_price_result(
                'a_plan_iceberg_shows_four_and_sends_the_next_piece_on_each_fill',
                {
                    'order': {
                        'presets': [
                            {
                                'iceberg': {
                                    'slice_quantity': 4,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 4)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'COMPLETE', 4)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000103', 'COMPLETE', 2)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_sends_four_slices_thirty_seconds_apart',
                {
                    'order': {
                        'presets': [
                            {
                                'twap': {
                                    'slices': 4,
                                    'over_minutes': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 10},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 60},
                    {'quote': steady, 'at': 90},
                    {'quote': steady, 'at': 120},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_whose_slices_are_icebergs_shows_two_at_a_time',
                {
                    'order': {
                        'execution': [
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                            {
                                'iceberg': {
                                    'visible_quantity': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 31, 'updates': [self.update('26091500000104', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 32, 'updates': [self.update('26091500000105', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 33, 'updates': [self.update('26091500000103', 'COMPLETE', 1), self.update('26091500000106', 'COMPLETE', 1)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_whose_slices_are_icebergs_survives_restarts',
                {
                    'order': {
                        'execution': [
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                            {
                                'iceberg': {
                                    'visible_quantity': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 31, 'updates': [self.update('26091500000104', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 32, 'updates': [self.update('26091500000105', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 33, 'updates': [self.update('26091500000103', 'COMPLETE', 1), self.update('26091500000106', 'COMPLETE', 1)]},
                ],
                numbered,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_iceberg_whose_slices_are_twaps_releases_the_next_once_one_fills',
                {
                    'order': {
                        'execution': [
                            {
                                'iceberg': {
                                    'visible_quantity': 5,
                                },
                            },
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 31, 'updates': [self.update('26091500000101', 'COMPLETE', 3), self.update('26091500000102', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 61},
                    {'quote': steady, 'at': 91},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_using_a_ladder_gives_every_rung_its_own_bracket',
                {
                    'using': {
                        'order': {
                            'execution': [
                                {
                                    'ladder': {
                                        'from_price': 1000,
                                        'to_price': 990,
                                        'steps': 2,
                                    },
                                },
                            ],
                        },
                        'each_piece': {
                            'presets': [
                                {
                                    'bracket': {
                                        'stop_price': 980,
                                        'stop_limit_price': 978,
                                        'target_price': 1020,
                                    },
                                },
                            ],
                        },
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000102', 'COMPLETE', 5)]},
                    {'quote': steady, 'at': 2},
                ],
                numbered,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_using_a_twap_covers_every_slice_with_its_own_stop',
                {
                    'using': {
                        'order': {
                            'execution': [
                                {
                                    'twap': {
                                        'slices': 2,
                                        'over_minutes': 1,
                                    },
                                },
                            ],
                        },
                        'each_piece': {
                            'presets': [
                                {
                                    'cover': {
                                        'stop_price': 980,
                                        'stop_limit_price': 978,
                                    },
                                },
                            ],
                        },
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 5)]},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 31, 'updates': [self.update('26091500000103', 'COMPLETE', 5)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_using_an_iceberg_or_a_priced_ladder_is_refused',
                {
                    'together': {
                        'children': [
                            {
                                'using': {
                                    'order': {
                                        'execution': [
                                            {
                                                'iceberg': {
                                                    'visible_quantity': 2,
                                                },
                                            },
                                        ],
                                    },
                                    'each_piece': {},
                                },
                            },
                            {
                                'using': {
                                    'order': {
                                        'execution': [
                                            {
                                                'ladder': {
                                                    'from_price': 1000,
                                                    'to_price': 990,
                                                    'steps': 2,
                                                },
                                            },
                                        ],
                                    },
                                    'each_piece': {
                                        'pricing': [
                                            {
                                                'marketable': {},
                                            },
                                        ],
                                    },
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_with_three_nested_executions_or_a_ladder_outside_is_refused',
                {
                    'together': {
                        'children': [
                            {
                                'order': {
                                    'execution': [
                                        {
                                            'twap': {
                                                'slices': 2,
                                                'over_minutes': 1,
                                            },
                                        },
                                        {
                                            'iceberg': {
                                                'visible_quantity': 2,
                                            },
                                        },
                                        {
                                            'iceberg': {
                                                'visible_quantity': 1,
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                'order': {
                                    'execution': [
                                        {
                                            'ladder': {
                                                'from_price': 1000,
                                                'to_price': 990,
                                                'steps': 2,
                                            },
                                        },
                                        {
                                            'iceberg': {
                                                'visible_quantity': 2,
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_keeps_its_schedule_across_a_restart',
                {
                    'order': {
                        'presets': [
                            {
                                'twap': {
                                    'slices': 4,
                                    'over_minutes': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 10},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 60},
                    {'quote': steady, 'at': 90},
                ],
                numbered,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_vwap_sizes_slices_by_the_half_hour_they_fall_in',
                {
                    'order': {
                        'presets': [
                            {
                                'vwap': {
                                    'slices': 3,
                                    'over_minutes': 60,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1200},
                    {'quote': steady, 'at': 2400},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_vwap_on_a_commodity_with_no_profile_of_its_own_sends_even_slices',
                {
                    'order': {
                        'presets': [
                            {
                                'vwap': {
                                    'slices': 4,
                                    'over_minutes': 60,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 900},
                    {'quote': steady, 'at': 1800},
                    {'quote': steady, 'at': 2700},
                ],
                numbered,
                body_overrides={
                    'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['crudeoil_future'],
                    'quantity': 400,
                },
            ),
            self.plan_price_result(
                'a_plan_implementation_shortfall_front_loads_its_slices',
                {
                    'order': {
                        'presets': [
                            {
                                'implementation_shortfall': {
                                    'slices': 3,
                                    'over_minutes': 3,
                                    'urgency': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 60},
                    {'quote': steady, 'at': 120},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_trailing_exit_sells_through_twap_once_the_price_pulls_back',
                {
                    'order': {
                        'side': 'protect',
                        'trigger': {
                            'trails': {
                                'points': 5,
                            },
                        },
                        'pricing': [
                            {
                                'marketable': {
                                    'buffer_ticks': 2,
                                },
                            },
                        ],
                        'execution': [
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 0},
                    {'quote': self.book_at(1005.95, 1006.00), 'at': 1},
                    {'quote': self.book_at(1000.90, 1000.95), 'at': 2},
                    {'quote': self.book_at(1000.50, 1000.55), 'at': 20},
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 32},
                ],
                numbered,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_bracket_whose_entry_is_an_iceberg_grows_its_exits_with_each_piece',
                {
                    'order': {
                        'presets': [
                            {
                                'iceberg': {
                                    'slice_quantity': 6,
                                },
                            },
                            {
                                'bracket': {
                                    'stop_price': 990,
                                    'stop_limit_price': 988,
                                    'target_price': 1010,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 6)]},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000102', 'COMPLETE', 4)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_that_slices_a_resting_stop_is_refused',
                {
                    'either': {
                        'sibling_rule': 'cancel',
                        'children': [
                            {
                                'order': {
                                    'side': 'protect',
                                    'pricing': [
                                        {
                                            'native_stop': {
                                                'trigger_price': 990,
                                                'limit_price': 988,
                                            },
                                        },
                                    ],
                                    'execution': [
                                        {
                                            'iceberg': {
                                                'visible_quantity': 2,
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                'order': {
                                    'execution': [
                                        {
                                            'twap': {
                                                'slices': 2,
                                                'over_minutes': 1,
                                            },
                                        },
                                        {
                                            'iceberg': {
                                                'visible_quantity': 2,
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                numbered,
            ),
        ]

    def with_volume(self, quote, volume):
        """A quote with the day's traded volume set, for an execution that follows it.

        Args:
            quote (dict): The quote.
            volume (int): The day's traded volume.

        Returns:
            dict: A copy of the quote carrying the volume.
        """
        carrying = dict(quote)
        carrying['volume'] = volume
        return carrying

    def run_plan_market_execution_checks(self):
        """Runs plans whose pieces follow the market: participation in traded volume, and strikes on displayed size.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        participation = {
            'order': {
                'presets': [
                    {
                        'participation': {
                            'participation_percent': 10,
                        },
                    },
                ],
            },
        }
        volume_steps = [
            {'quote': self.with_volume(steady, 1000), 'at': 0},
            {'quote': self.with_volume(steady, 1050), 'at': 1},
            {'quote': self.with_volume(steady, 1060), 'at': 2},
            {'quote': self.with_volume(steady, 1062), 'at': 3},
            {'quote': self.with_volume(steady, 1110), 'at': 4},
        ]
        return [
            self.plan_price_result(
                'a_plan_participation_sends_ten_percent_of_the_volume_traded',
                participation,
                volume_steps,
                numbered,
            ),
            self.plan_price_result(
                'a_plan_participation_keeps_its_count_across_a_restart',
                participation,
                volume_steps,
                numbered,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_liquidity_seeking_waits_for_size_inside_its_limit',
                {
                    'order': {
                        'presets': [
                            {
                                'liquidity_seeking': {
                                    'limit_price': 1000.10,
                                    'minimum_quantity': 50,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(999.95, 1000.20), 'at': 0},
                    {'quote': self.book_at(999.95, 1000.20), 'at': 1},
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 2},
                    {'quote': self.book_at(1000.00, 1000.05), 'at': 3},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_participation_that_starts_at_a_time',
                {
                    'order': {
                        'presets': [
                            {
                                'scheduled': {
                                    'at_time': '10:00:30',
                                },
                            },
                            {
                                'participation': {
                                    'participation_percent': 10,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.with_volume(steady, 1000), 'at': 0},
                    {'quote': self.with_volume(steady, 1100), 'at': 10},
                    {'quote': self.with_volume(steady, 1200), 'at': 40},
                    {'quote': self.with_volume(steady, 1250), 'at': 41},
                ],
                numbered,
            ),
        ]

    def run_plan_moving_price_checks(self):
        """Runs plans whose price moves after the order rests, a cap that holds it, and the post-only guard, each beside the type it stands for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        numbered = dict(
            accepted,
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        chaser = {
            'order': {
                'presets': [
                    {
                        'chaser': {
                            'step_ticks': 1,
                            'step_seconds': 5,
                        },
                    },
                ],
            },
        }
        chaser_steps = [
            {'quote': steady, 'at': 0},
            {'quote': steady, 'at': 1},
            {'quote': steady, 'at': 6},
            {'quote': steady, 'at': 7},
            {'quote': steady, 'at': 12},
        ]
        return [
            self.plan_price_result(
                'a_plan_peg_follows_the_bid_it_is_pegged_to',
                {
                    'order': {
                        'presets': [
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 1},
                    {'quote': self.book_at(999.80, 999.85), 'at': 2},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_peg_will_not_follow_the_bid_past_its_cap',
                {
                    'order': {
                        'presets': [
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                    'cap_price': 1000.10,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.50, 1000.55), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_peg_to_the_midpoint_rests_between_the_touch',
                {
                    'order': {
                        'presets': [
                            {
                                'peg': {
                                    'reference': 'mid',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.10), 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.30), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_chaser_steps_towards_the_market_when_its_wait_is_up',
                chaser,
                chaser_steps,
                accepted,
            ),
            self.plan_price_result(
                'a_plan_chaser_keeps_its_clock_across_a_restart',
                chaser,
                chaser_steps,
                accepted,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_chaser_will_not_step_past_its_cap',
                {
                    'order': {
                        'presets': [
                            {
                                'chaser': {
                                    'step_ticks': 1,
                                    'step_seconds': 5,
                                    'cap_price': 1000.05,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 6},
                    {'quote': steady, 'at': 12},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_chaser_crosses_when_its_time_is_up',
                {
                    'order': {
                        'presets': [
                            {
                                'chaser': {
                                    'step_ticks': 1,
                                    'step_seconds': 5,
                                    'cross_after_seconds': 10,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 6},
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 11},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_post_only_refuses_a_price_that_would_cross',
                {
                    'order': {
                        'presets': [
                            {
                                'post_only': {},
                            },
                        ],
                        'pricing': [
                            {
                                'fixed': {
                                    'price': 1000.10,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_post_only_can_be_told_to_rest_at_the_touch_instead',
                {
                    'order': {
                        'presets': [
                            {
                                'post_only': {
                                    'on_crossing': 'rest',
                                },
                            },
                        ],
                        'pricing': [
                            {
                                'fixed': {
                                    'price': 1000.10,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_post_only_with_a_marketable_price_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 1001,
                                },
                            },
                            {
                                'post_only': {},
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_twap_pegs_every_resting_slice_to_the_bid',
                {
                    'order': {
                        'presets': [
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.10, 1000.15), 'at': 1},
                    {'quote': self.book_at(1000.10, 1000.15), 'at': 30},
                    {'quote': self.book_at(999.90, 999.95), 'at': 31},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_scheduled_peg_rests_at_its_time_and_then_follows',
                {
                    'order': {
                        'presets': [
                            {
                                'scheduled': {
                                    'at_time': '10:00:30',
                                },
                            },
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                    'offset_ticks': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 40},
                    {'quote': self.book_at(1000.30, 1000.35), 'at': 41},
                ],
                accepted,
            ),
        ]

    def run_plan_followed_price_checks(self):
        """Runs plans priced from another instrument or an option model, and plans with discretion, each beside the type it stands for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        steady = self.book_at(1000.00, 1000.05)
        underlying_peg = {
            'order': {
                'presets': [
                    {
                        'underlying_peg': {
                            'watch_instrument_id': identifiers['nifty_index'],
                            'delta': 0.5,
                            'step_ticks': 20,
                        },
                    },
                ],
            },
        }
        underlying_steps = [
            {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
            {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25040)}},
            {'quote': steady, 'at': 2, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25041)}},
            {'quote': steady, 'at': 3, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=24960)}},
        ]
        option = {
            'instrument_id': identifiers['nifty_option'],
            'quantity': 75,
            'price': 500,
        }
        volatility = {
            'order': {
                'presets': [
                    {
                        'volatility': {
                            'watch_instrument_id': identifiers['nifty_index'],
                            'volatility': 12.5,
                        },
                    },
                ],
            },
        }
        discretionary = {
            'order': {
                'presets': [
                    {
                        'discretionary': {
                            'discretion_points': 0.25,
                        },
                    },
                ],
            },
        }
        return [
            self.plan_price_result(
                'a_plan_underlying_peg_moves_with_the_index_by_its_delta',
                underlying_peg,
                underlying_steps,
                accepted,
            ),
            self.plan_price_result(
                'a_plan_underlying_peg_keeps_its_start_across_a_restart',
                underlying_peg,
                underlying_steps,
                accepted,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_underlying_peg_stays_inside_its_range',
                {
                    'order': {
                        'presets': [
                            {
                                'underlying_peg': {
                                    'watch_instrument_id': identifiers['nifty_index'],
                                    'delta': 0.5,
                                    'highest_price': 1010,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25100)}},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_underlying_peg_on_its_own_instrument_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'underlying_peg': {
                                    'watch_instrument_id': identifiers['reliance'],
                                    'delta': 0.5,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_volatility_order_is_priced_by_the_model_and_follows_the_index',
                volatility,
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 2, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25100)}},
                ],
                accepted,
                body_overrides=option,
            ),
            self.plan_price_result(
                'a_plan_volatility_order_never_pays_more_than_its_own_price',
                volatility,
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=24900)}},
                ],
                accepted,
                body_overrides=dict(option, price=150),
            ),
            self.plan_price_result(
                'a_plan_volatility_order_on_something_that_is_not_an_option_is_refused',
                volatility,
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_discretionary_order_takes_the_offer_when_it_comes_within_reach',
                discretionary,
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.20), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_discretionary_order_leaves_the_rest_showing_when_it_takes_a_slice',
                {
                    'order': {
                        'presets': [
                            {
                                'discretionary': {
                                    'discretion_points': 0.25,
                                    'discretion_quantity': 4,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.20), 'at': 1},
                    {'quote': self.book_at(1000.00, 1000.20), 'at': 2},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_discretionary_order_waits_while_the_offer_stays_out_of_reach',
                discretionary,
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.40), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_discretionary_order_sliced_by_twap_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'discretionary': {
                                    'discretion_points': 0.25,
                                },
                            },
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
        ]

    def run_plan_stage_stop_checks(self):
        """Runs plans whose stop trails the recent average range, moves through profit milestones, or waits for a bar to close past its level, each beside the type it stands for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        stop_book = {
            'order_type': 'SL',
            'trigger_price': 990.0,
        }
        stepped = {
            'order': {
                'presets': [
                    {
                        'stepped_stop': {
                            'entry_price': 1000,
                            'stop_price': 990,
                            'stop_limit_offset': 2,
                            'rules': [
                                {
                                    'gain': 20,
                                    'stop_at_gain': 0,
                                },
                                {
                                    'gain': 40,
                                    'stop_at_gain': 15,
                                },
                                {
                                    'gain': 60,
                                    'trail_points': 25,
                                },
                            ],
                        },
                    },
                ],
            },
        }
        candle = {
            'order': {
                'presets': [
                    {
                        'candle_close_stop': {
                            'trigger_price': 995,
                            'bar_minutes': 1,
                        },
                    },
                ],
            },
        }
        stepped_steps = [
            {'quote': steady, 'at': 0},
            {'quote': self.book_at(1024.95, 1025.00), 'at': 1},
            {'quote': self.book_at(1044.95, 1045.00), 'at': 2},
            {'quote': self.book_at(1029.95, 1030.00), 'at': 3},
            {'quote': self.book_at(1069.95, 1070.00), 'at': 4},
            {'quote': self.book_at(1079.95, 1080.00), 'at': 5},
        ]
        return [
            self.plan_price_result(
                'a_plan_average_range_trail_uses_its_fixed_fallback_until_it_has_bars',
                {
                    'order': {
                        'presets': [
                            {
                                'atr_trail': {
                                    'trail_points': 10,
                                    'stop_limit_offset': 2,
                                    'bar_minutes': 1,
                                    'periods': 2,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 1},
                ],
                accepted,
                positions=10,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
            ),
            self.plan_price_result(
                'a_plan_average_range_trail_widens_once_enough_bars_have_closed',
                {
                    'order': {
                        'presets': [
                            {
                                'atr_trail': {
                                    'trail_points': 10,
                                    'stop_limit_offset': 2,
                                    'bar_minutes': 1,
                                    'periods': 2,
                                    'atr_multiple': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1040.00, 1040.05), 'at': 10},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 70},
                    {'quote': self.book_at(1060.00, 1060.05), 'at': 130},
                    {'quote': self.book_at(1080.00, 1080.05), 'at': 190},
                ],
                accepted,
                positions=10,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
            ),
            self.plan_price_result(
                'a_plan_stepped_stop_moves_at_each_milestone_and_then_trails',
                stepped,
                stepped_steps,
                accepted,
                positions=10,
                book_overrides=stop_book,
            ),
            self.plan_price_result(
                'a_plan_stepped_stop_keeps_its_milestones_across_a_restart',
                stepped,
                stepped_steps,
                accepted,
                positions=10,
                book_overrides=stop_book,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_stepped_stop_that_jumps_past_every_milestone_starts_trailing',
                stepped,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1064.95, 1065.00), 'at': 1},
                ],
                accepted,
                positions=10,
                book_overrides=stop_book,
            ),
            self.plan_price_result(
                'a_plan_candle_close_stop_sits_through_a_wick',
                candle,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 10},
                    {'quote': steady, 'at': 50},
                    {'quote': steady, 'at': 70},
                ],
                accepted,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_candle_close_stop_fires_on_a_bar_that_closed_below',
                candle,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 10},
                    {'quote': self.book_at(990.00, 990.05), 'at': 50},
                    {'quote': self.book_at(990.00, 990.05), 'at': 70},
                ],
                accepted,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_candle_close_stop_with_a_backstop_cancels_it_before_exiting',
                {
                    'order': {
                        'presets': [
                            {
                                'candle_close_stop': {
                                    'trigger_price': 995,
                                    'bar_minutes': 1,
                                    'backstop_price': 980,
                                    'backstop_limit_price': 978,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 10},
                    {'quote': self.book_at(990.00, 990.05), 'at': 70},
                    {'quote': self.book_at(990.00, 990.05), 'at': 71},
                ],
                accepted,
                positions=10,
                book_overrides=stop_book,
            ),
            self.plan_price_result(
                'a_plan_good_till_triggered_order_fires_on_the_day_the_level_is_touched',
                {
                    'order': {
                        'presets': [
                            {
                                'good_till_triggered': {
                                    'trigger_price': 995,
                                    'limit_price': 990,
                                    'valid_days': 30,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_good_till_triggered_order_expires_once_it_has_waited_long_enough',
                {
                    'order': {
                        'presets': [
                            {
                                'good_till_triggered': {
                                    'trigger_price': 900,
                                    'limit_price': 890,
                                    'valid_days': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 60 * 60 * 25},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_stepped_stop_with_a_trail_before_its_last_rule_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'stepped_stop': {
                                    'entry_price': 1000,
                                    'stop_price': 990,
                                    'stop_limit_offset': 2,
                                    'rules': [
                                        {
                                            'gain': 20,
                                            'trail_points': 10,
                                        },
                                        {
                                            'gain': 40,
                                            'stop_at_gain': 15,
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=10,
            ),
            self.plan_price_result(
                'a_plan_stepped_stop_rule_that_would_fire_at_once_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'stepped_stop': {
                                    'entry_price': 1000,
                                    'stop_price': 990,
                                    'stop_limit_offset': 2,
                                    'rules': [
                                        {
                                            'gain': 20,
                                            'stop_at_gain': 20,
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=10,
            ),
        ]

    def run_plan_lifetime_checks(self):
        """Runs plans whose orders end at a time: cancelled, made marketable, or with what filled closed, each beside the type it stands for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        frozen = FROZEN_NOW.timestamp()
        sunday = FROZEN_NOW.replace(day=27)
        time_stop = {
            'order': {
                'presets': [
                    {
                        'time_stop': {
                            'until_time': '10:30',
                        },
                    },
                ],
            },
        }
        return [
            self.plan_clock_result(
                'a_plan_good_till_time_order_is_cancelled_when_it_runs_out',
                {
                    'order': {
                        'presets': [
                            {
                                'good_till_time': {
                                    'until_time': '10:30',
                                },
                            },
                        ],
                    },
                },
                [],
                frozen + 1900,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_limit_then_market_order_is_made_marketable_when_its_time_comes',
                {
                    'order': {
                        'presets': [
                            {
                                'good_till_time': {
                                    'until_time': '10:30',
                                    'at_expiry': 'market',
                                },
                            },
                        ],
                    },
                },
                [],
                frozen + 1900,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.plan_clock_result(
                'a_plan_good_till_time_order_taken_on_a_sunday_cancels_on_monday',
                {
                    'order': {
                        'presets': [
                            {
                                'good_till_time': {
                                    'until_time': '14:30',
                                },
                            },
                        ],
                    },
                },
                [],
                sunday.replace(hour=14, minute=31).timestamp(),
                accepted,
                taken_at=sunday,
            ),
            self.plan_clock_result(
                'a_plan_time_stop_in_minutes_on_a_sunday_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'time_stop': {
                                    'minutes': 20,
                                },
                            },
                        ],
                    },
                },
                [],
                sunday.replace(hour=11).timestamp(),
                accepted,
                taken_at=sunday,
            ),
            self.plan_clock_result(
                'a_plan_time_stop_closes_what_it_filled',
                time_stop,
                [
                    self.update('26091500000021', 'OPEN', 6),
                ],
                frozen + 1900,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_time_stop_that_filled_nothing_just_cancels',
                time_stop,
                [],
                frozen + 1900,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_waiting_order_runs_out_of_time_before_its_trigger',
                {
                    'order': {
                        'presets': [
                            {
                                'limit_if_touched': {
                                    'trigger_price': 1050,
                                    'limit_price': 1050,
                                },
                            },
                            {
                                'good_till_time': {
                                    'until_time': '10:30',
                                },
                            },
                        ],
                    },
                },
                [],
                frozen + 1900,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_time_stop_inside_a_bracket_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'bracket': {
                                    'stop_price': 990,
                                    'stop_limit_price': 988,
                                    'target_price': 1010,
                                },
                            },
                            {
                                'time_stop': {
                                    'until_time': '10:30',
                                },
                            },
                        ],
                    },
                },
                [],
                frozen + 1900,
                accepted,
            ),
        ]

    def run_plan_change_checks(self):
        """Runs a caller's changes to a plan through `PUT /api/orders/modify`: to broker orders the plan placed, which it must carry on from rather than undo, and to parts it has not yet sent.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        stop_in_the_book = {
            'order_type': 'SL',
            'trigger_price': 995.05,
        }
        trailing = {
            'order': {
                'presets': [
                    {
                        'trailing_stop': {
                            'trail_points': 5,
                            'stop_limit_offset': 1,
                        },
                    },
                ],
            },
        }
        bracket = {
            'order': {
                'presets': [
                    {
                        'bracket': {
                            'stop_price': 990,
                            'stop_limit_price': 988,
                            'target_price': 1010,
                        },
                    },
                ],
            },
        }
        stop_part = 'root.each_fill.children.0'
        trailing_steps = [
            {'quote': steady, 'at': 0},
            {'quote': self.book_at(1005.95, 1006.00), 'at': 1},
            {'quote': self.book_at(1001.95, 1002.00), 'at': 2, 'leg_change': {'order_id': '26091500000101', 'trigger_price': '995', 'price': '994'}},
            {'quote': self.book_at(1001.95, 1002.00), 'at': 3},
            {'quote': self.book_at(1003.95, 1004.00), 'at': 4},
        ]
        return [
            self.plan_price_result(
                'a_plan_trailing_stop_carries_on_from_the_trigger_the_caller_set',
                trailing,
                trailing_steps,
                numbered,
                positions=10,
                book_overrides=stop_in_the_book,
            ),
            self.plan_price_result(
                'a_plan_trailing_stop_keeps_the_callers_trigger_across_a_restart',
                trailing,
                trailing_steps,
                numbered,
                positions=10,
                book_overrides=stop_in_the_book,
                restart_between_ticks=True,
            ),
            self.plan_price_result(
                'a_plan_peg_rests_where_the_caller_moved_it',
                {
                    'order': {
                        'presets': [
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'leg_change': {'order_id': '26091500000101', 'price': '999.50'}},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 2},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_chase_waits_a_full_step_after_the_callers_price',
                {
                    'order': {
                        'presets': [
                            {
                                'chaser': {
                                    'step_ticks': 1,
                                    'step_seconds': 5,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                    {'quote': steady, 'at': 5.5, 'leg_change': {'order_id': '26091500000101', 'price': '999.00'}},
                    {'quote': steady, 'at': 7},
                    {'quote': steady, 'at': 11},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_bracket_exit_cut_brings_the_other_down_and_stays_cut',
                bracket,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 2, 'leg_change': {'order_id': '26091500000103', 'quantity': 6}},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000103', 'OPEN', 2)]},
                    {'quote': steady, 'at': 4, 'leg_change': {'order_id': '26091500000102', 'quantity': 15}},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_iceberg_slice_change_keeps_the_total',
                {
                    'order': {
                        'presets': [
                            {
                                'iceberg': {
                                    'slice_quantity': 4,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'leg_change': {'order_id': '26091500000101', 'quantity': 2}},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 3, 'updates': [self.update('26091500000102', 'COMPLETE', 4)]},
                    {'quote': steady, 'at': 4, 'updates': [self.update('26091500000103', 'COMPLETE', 4)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_order_cut_by_the_caller_completes_at_the_new_quantity',
                {
                    'order': {},
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'leg_change': {'order_id': '26091500000101', 'quantity': 6}},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'COMPLETE', 6)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_bracket_stop_moved_before_the_entry_fills',
                bracket,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'held_change': {'part': stop_part, 'trigger_price': '985', 'price': '983'}},
                    {'quote': steady, 'at': 2, 'held_change': {'part': stop_part, 'quantity': 5}},
                    {'quote': steady, 'at': 3, 'held_change': {'part': 'root.first', 'price': '999'}},
                    {'quote': steady, 'at': 4, 'held_change': {'part': 'root.each_fill.children.1', 'trigger_price': '1012'}},
                    {'quote': steady, 'at': 5, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 6},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_waiting_order_cut_before_its_trigger',
                {
                    'order': {
                        'presets': [
                            {
                                'market_if_touched': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'held_change': {'part': 'root', 'quantity': 6, 'dry_run': True}},
                    {'quote': steady, 'at': 2, 'held_change': {'part': 'root', 'quantity': 6}},
                    {'quote': steady, 'at': 3, 'held_change': {'part': 'root', 'price': '994'}},
                    {'quote': steady, 'at': 4, 'held_change': {'part': 'nowhere', 'price': '994'}},
                    {'quote': self.book_at(994.90, 994.95), 'at': 5},
                ],
                numbered,
            ),
            self.price_result(
                'a_simple_order_has_no_parts_to_change',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='MARKET',
                    quantity=10,
                    synthetic={
                        'type': 'simple',
                    },
                ),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'held_change': {'part': 'root', 'quantity': 6}},
                ],
                numbered,
            ),
        ]

    def run_plan_cancel_checks(self):
        """Runs a caller's cancels of a plan through `DELETE /api/orders/cancel`: of one part, sent or not, which must stop it sending anything more, and of one broker order, which the plan must not send again.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        steady = self.book_at(1000.00, 1000.05)
        bracket = {
            'order': {
                'presets': [
                    {
                        'bracket': {
                            'stop_price': 990,
                            'stop_limit_price': 988,
                            'target_price': 1010,
                        },
                    },
                ],
            },
        }
        twap = {
            'order': {
                'presets': [
                    {
                        'twap': {
                            'slices': 4,
                            'over_minutes': 2,
                        },
                    },
                ],
            },
        }
        stop_part = 'root.each_fill.children.0'
        return [
            self.plan_price_result(
                'a_plan_bracket_stop_cancelled_before_the_entry_fills_is_never_sent',
                bracket,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': stop_part, 'dry_run': True}},
                    {'quote': steady, 'at': 2, 'part_cancel': {'part': stop_part}},
                    {'quote': steady, 'at': 3, 'part_cancel': {'part': stop_part}},
                    {'quote': steady, 'at': 4, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 5},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_bracket_entry_cancelled_while_it_rests_drops_its_exits',
                bracket,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': 'root.first'}},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'CANCELLED', 0)]},
                    {'quote': steady, 'at': 3},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_cancelled_by_part_sends_no_more_slices',
                twap,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 31, 'updates': [self.update('26091500000101', 'COMPLETE', 3)]},
                    {'quote': steady, 'at': 40, 'part_cancel': {'part': 'root'}},
                    {'quote': steady, 'at': 41, 'updates': [self.update('26091500000102', 'CANCELLED', 0)]},
                    {'quote': steady, 'at': 60},
                    {'quote': steady, 'at': 90},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_twap_slice_cancelled_by_order_id_is_skipped_and_the_rest_carry_on',
                twap,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 10, 'leg_cancel': '26091500000101'},
                    {'quote': steady, 'at': 11, 'updates': [self.update('26091500000101', 'CANCELLED', 0)]},
                    {'quote': steady, 'at': 30},
                    {'quote': steady, 'at': 60},
                    {'quote': steady, 'at': 90},
                    {'quote': steady, 'at': 91, 'updates': [self.update('26091500000102', 'COMPLETE', 3), self.update('26091500000103', 'COMPLETE', 2), self.update('26091500000104', 'COMPLETE', 2)]},
                    {'quote': steady, 'at': 150},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_iceberg_slice_cancelled_by_order_id_shows_no_more',
                {
                    'order': {
                        'presets': [
                            {
                                'iceberg': {
                                    'slice_quantity': 4,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'leg_cancel': '26091500000101'},
                    {'quote': steady, 'at': 2, 'updates': [self.update('26091500000101', 'CANCELLED', 0)]},
                    {'quote': steady, 'at': 3},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_peg_cancelled_by_part_is_not_moved_while_the_cancel_is_confirmed',
                {
                    'order': {
                        'presets': [
                            {
                                'peg': {
                                    'reference': 'own_touch',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': 'root'}},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 2},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 3, 'updates': [self.update('26091500000101', 'CANCELLED', 0)]},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_whole_parent_cancel_dry_run_names_its_resting_orders',
                bracket,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000101', 'COMPLETE', 10)]},
                    {'quote': steady, 'at': 2, 'part_cancel': {'dry_run': True}},
                    {'quote': steady, 'at': 3, 'part_cancel': {'part': 'nowhere'}},
                ],
                numbered,
            ),
            self.plan_price_result(
                'a_plan_kept_whole_exits_cannot_be_cancelled_before_they_start',
                {
                    'order': {
                        'presets': [
                            {
                                'scale_out': {
                                    'stop_price': 990,
                                    'stop_limit_price': 988,
                                    'target_prices': [
                                        1010,
                                        1020,
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': 'root.each_fill'}},
                ],
                numbered,
            ),
            self.price_result(
                'a_simple_order_has_no_parts_to_cancel',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='MARKET',
                    quantity=10,
                    synthetic={
                        'type': 'simple',
                    },
                ),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'part_cancel': {'part': 'root'}},
                ],
                numbered,
            ),
        ]

    def run_plan_group_checks(self):
        """Runs plans whose orders trade several instruments: a basket, a one-cancels-all group, a sequence, and a group done when any order is, beside the types they stand for.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        basket_candidates = [
            {
                'instrument_id': identifiers['reliance'],
                'quantity': 10,
                'price': 1000,
            },
            {
                'instrument_id': identifiers['kwil'],
                'quantity': 5,
                'price': 250,
            },
            {
                'instrument_id': identifiers['nifty_option'],
                'transaction_type': 'SELL',
                'quantity': 75,
                'price': 120,
            },
        ]
        return [
            self.plan_result(
                'a_plan_basket_places_every_leg_and_reports_each_one',
                {
                    'order': {
                        'presets': [
                            {
                                'basket': {
                                    'candidates': basket_candidates,
                                },
                            },
                        ],
                    },
                },
                [],
                numbered,
            ),
            self.plan_result(
                'a_plan_basket_refuses_a_repeated_instrument',
                {
                    'order': {
                        'presets': [
                            {
                                'basket': {
                                    'candidates': [
                                        {
                                            'instrument_id': identifiers['reliance'],
                                            'quantity': 10,
                                        },
                                        {
                                            'instrument_id': identifiers['reliance'],
                                            'quantity': 5,
                                            'price': 995,
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [],
                numbered,
            ),
            self.plan_result(
                'a_plan_one_cancels_all_group_calls_off_the_rest_on_the_first_fill',
                {
                    'order': {
                        'presets': [
                            {
                                'oca': {
                                    'candidates': [
                                        {
                                            'instrument_id': identifiers['reliance'],
                                            'quantity': 10,
                                            'price': 1000,
                                        },
                                        {
                                            'instrument_id': identifiers['kwil'],
                                            'quantity': 5,
                                            'price': 250,
                                        },
                                        {
                                            'instrument_id': identifiers['sensex_option'],
                                            'quantity': 20,
                                            'price': 80,
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    self.update('26091500000101', 'OPEN', 4),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_order_can_trade_another_instrument',
                {
                    'order': {
                        'instrument_id': identifiers['kwil'],
                        'quantity': 5,
                        'pricing': [
                            {
                                'fixed': {
                                    'price': 250,
                                },
                            },
                        ],
                    },
                },
                [],
                numbered,
            ),
            self.plan_result(
                'a_plan_sequence_sends_its_second_order_once_the_first_is_done',
                {
                    'sequence': {
                        'children': [
                            {
                                'order': {
                                    'transaction_type': 'SELL',
                                },
                            },
                            {
                                'order': {
                                    'instrument_id': identifiers['kwil'],
                                    'quantity': 5,
                                    'pricing': [
                                        {
                                            'fixed': {
                                                'price': 250,
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    self.update('26091500000101', 'OPEN', 4),
                    self.update('26091500000101', 'COMPLETE', 10),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_group_done_when_any_order_is_cancels_the_rest',
                {
                    'together': {
                        'done_when': 'any',
                        'group_margin': False,
                        'children': [
                            {
                                'order': {},
                            },
                            {
                                'order': {
                                    'instrument_id': identifiers['kwil'],
                                    'quantity': 5,
                                    'pricing': [
                                        {
                                            'fixed': {
                                                'price': 250,
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
                [
                    self.update('26091500000101', 'COMPLETE', 10),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_then_whose_child_is_a_group_is_refused',
                {
                    'then': {
                        'first': {
                            'order': {},
                        },
                        'each_fill': {
                            'together': {
                                'children': [
                                    {
                                        'order': {},
                                    },
                                ],
                            },
                        },
                    },
                },
                [],
                numbered,
            ),
        ]

    def run_plan_close_checks(self):
        """Runs plans that close the position held when they fire: on a price, at a time, and reversed, beside the types they stand for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        steady = self.book_at(1000.00, 1000.05)
        frozen = FROZEN_NOW.timestamp()
        close_at_995 = {
            'order': {
                'presets': [
                    {
                        'close_on_trigger': {
                            'trigger_price': 995,
                        },
                    },
                ],
            },
        }
        square_off = {
            'order': {
                'presets': [
                    {
                        'square_off': {
                            'at_time': '15:10',
                        },
                    },
                ],
            },
        }
        doubled = {
            'order': {
                'presets': [
                    {
                        'stop_and_reverse': {
                            'trigger_price': 995,
                            'method': 'double',
                        },
                    },
                ],
            },
        }
        return [
            self.plan_price_result(
                'a_plan_close_on_trigger_cancels_resting_orders_then_closes_the_long',
                close_at_995,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.00, 994.05), 'at': 2},
                ],
                accepted,
                positions=75,
                resting=[
                    '26091500000077',
                ],
            ),
            self.plan_price_result(
                'a_plan_close_on_trigger_closes_a_position_split_across_brokers_at_each_broker',
                close_at_995,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions={
                    'flattrade': 50,
                    'zerodha': 25,
                },
            ),
            self.plan_price_result(
                'a_plan_close_on_trigger_with_nothing_held_completes_without_an_order',
                close_at_995,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions=0,
            ),
            self.plan_price_result(
                'a_plan_close_on_trigger_buys_back_a_short_when_the_price_rises',
                {
                    'order': {
                        'presets': [
                            {
                                'close_on_trigger': {
                                    'trigger_price': 1005,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1005.00, 1005.05), 'at': 1},
                ],
                accepted,
                positions=-40,
                transaction_type='SELL',
            ),
            self.plan_price_result(
                'a_plan_stop_and_reverse_closes_then_reverses_once_the_close_fills',
                {
                    'order': {
                        'presets': [
                            {
                                'stop_and_reverse': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.00, 994.05), 'at': 2},
                    {
                        'quote': self.book_at(994.00, 994.05),
                        'at': 3,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 75),
                        ],
                    },
                ],
                accepted,
                positions=75,
            ),
            self.plan_price_result(
                'a_plan_doubled_stop_and_reverse_sends_one_order_for_twice_the_position',
                doubled,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions=75,
            ),
            self.plan_price_result(
                'a_plan_doubled_stop_and_reverse_doubles_each_brokers_share_at_that_broker',
                doubled,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions={
                    'flattrade': 50,
                    'zerodha': 25,
                },
            ),
            self.plan_price_result(
                'a_plan_stop_and_reverse_with_an_unknown_method_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'stop_and_reverse': {
                                    'trigger_price': 995,
                                    'method': 'sideways',
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_square_off_cancels_what_is_resting_and_closes_what_is_held',
                square_off,
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
            ),
            self.plan_clock_result(
                'a_plan_square_off_records_the_cancel_of_an_order_placed_outside_the_engine',
                square_off,
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
                resting=[
                    '26091500000077',
                ],
            ),
            self.plan_clock_result(
                'a_plan_square_off_closes_a_position_split_across_brokers_at_each_broker',
                square_off,
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions={
                    'flattrade': 5,
                    'zerodha': 3,
                },
            ),
            self.plan_clock_result(
                'a_plan_square_off_with_nothing_held_closes_nothing',
                square_off,
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.plan_price_result(
                'a_plan_close_with_a_price_of_its_own_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'close_on_trigger': {
                                    'trigger_price': 995,
                                },
                            },
                        ],
                        'pricing': [
                            {
                                'fixed': {
                                    'price': 990,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=75,
            ),
        ]

    def run_plan_repeat_checks(self):
        """Runs plans that send one order again on a schedule, beside the accumulation and daily stop types they stand for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        frozen = FROZEN_NOW.timestamp()
        opening_auction = {
            'order': {
                'presets': [
                    {
                        'opening_auction': {},
                    },
                ],
            },
        }
        closing_price = {
            'order': {
                'presets': [
                    {
                        'closing_price': {},
                    },
                ],
            },
        }
        daily_stop = {
            'order': {
                'presets': [
                    {
                        'daily_stop': {
                            'stop_price': 990,
                            'stop_limit_price': 988,
                            'arm_at': '09:20',
                        },
                    },
                ],
            },
        }
        accumulation = {
            'order': {
                'presets': [
                    {
                        'accumulation': {
                            'every_minutes': 30,
                            'purchases': 4,
                        },
                    },
                ],
            },
        }
        return [
            self.plan_clock_result(
                'a_plan_accumulation_buys_again_when_its_gap_is_up',
                accumulation,
                [],
                frozen + 2000,
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                },
            ),
            self.plan_clock_result(
                'a_plan_accumulation_never_bids_above_the_callers_limit',
                accumulation,
                [],
                frozen + 60,
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                    'price': 995,
                },
                record_prices=True,
            ),
            self.plan_clock_result(
                'a_plan_accumulation_rests_on_the_bid_when_it_is_better_than_the_limit',
                accumulation,
                [],
                frozen + 60,
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                    'price': 1005,
                },
                record_prices=True,
            ),
            self.plan_clock_result(
                'a_plan_accumulation_with_no_bid_rests_at_the_callers_limit',
                accumulation,
                [],
                frozen + 60,
                accepted,
                quote=self.scenarios.quote(depth={
                    'buy': [],
                    'sell': [],
                }),
                body_overrides={
                    'quantity': 5,
                    'price': 995,
                },
                record_prices=True,
            ),
            self.plan_clock_result(
                'a_plan_accumulation_waits_out_the_gap_between_purchases',
                accumulation,
                [],
                frozen + 60,
                accepted,
                quote=self.scenarios.quote(),
                body_overrides={
                    'quantity': 5,
                },
            ),
            self.plan_clock_result(
                'a_plan_daily_stop_taken_on_a_sunday_places_nothing_that_day',
                daily_stop,
                [],
                FROZEN_NOW.replace(day=27).replace(hour=9, minute=21).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27).replace(hour=8, minute=45),
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.plan_clock_result(
                'a_plan_daily_stop_taken_after_its_time_waits_for_the_next_trading_morning',
                daily_stop,
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW,
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.plan_clock_result(
                'a_plan_daily_stop_places_a_fresh_stop_in_the_morning',
                daily_stop,
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.plan_clock_result(
                'a_plan_daily_stop_closes_the_position_when_the_open_gapped_past_it',
                daily_stop,
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                quote=self.scenarios.quote(
                    last_price=960.00,
                    depth={
                        'buy': [
                            {'price': 960.00, 'quantity': 100, 'orders': 1},
                        ],
                        'sell': [
                            {'price': 960.05, 'quantity': 100, 'orders': 1},
                        ],
                    },
                ),
                positions=10,
            ),
            self.plan_clock_result(
                'a_plan_closing_price_order_waits_for_the_window_and_then_slices',
                closing_price,
                [],
                FROZEN_NOW.replace(hour=15, minute=0).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=14, minute=30),
                body_overrides={
                    'quantity': 60,
                },
            ),
            self.plan_clock_result(
                'a_plan_closing_price_order_inside_the_window_starts_at_once',
                {
                    'order': {
                        'presets': [
                            {
                                'closing_price': {
                                    'slices': 4,
                                },
                            },
                        ],
                    },
                },
                [],
                FROZEN_NOW.replace(hour=15, minute=15).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=15, minute=10),
                body_overrides={
                    'quantity': 40,
                },
            ),
            self.plan_clock_result(
                'a_plan_closing_price_order_after_the_close_is_refused',
                closing_price,
                [],
                FROZEN_NOW.replace(hour=15, minute=32).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=15, minute=31),
            ),
            self.plan_clock_result(
                'a_plan_closing_price_window_starting_after_the_close_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'closing_price': {
                                    'window_start': '15:40',
                                },
                            },
                        ],
                    },
                },
                [],
                frozen + 60,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_closing_price_order_taken_on_a_sunday_is_scheduled_for_monday',
                closing_price,
                [],
                FROZEN_NOW.replace(day=27).replace(hour=15, minute=1).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.plan_clock_result(
                'a_plan_opening_auction_order_waits_for_the_pre_open',
                opening_auction,
                [],
                FROZEN_NOW.replace(hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
            ),
            self.plan_clock_result(
                'a_plan_opening_auction_order_after_collection_is_refused',
                opening_auction,
                [],
                frozen + 60,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_opening_auction_order_for_an_option_is_refused',
                opening_auction,
                [],
                FROZEN_NOW.replace(hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                body_overrides={
                    'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                },
            ),
            self.plan_clock_result(
                'a_plan_opening_auction_order_taken_on_a_sunday_joins_mondays_pre_open',
                opening_auction,
                [],
                FROZEN_NOW.replace(day=28, hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.plan_clock_result(
                'a_plan_repeat_whose_child_is_a_join_is_refused',
                {
                    'repeat': {
                        'child': {
                            'then': {
                                'first': {
                                    'order': {},
                                },
                                'each_fill': {
                                    'order': {},
                                },
                            },
                        },
                        'times': 2,
                        'every_minutes': 5,
                    },
                },
                [],
                frozen + 60,
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_repeat_every_trading_day_sends_its_first_copy_the_next_morning',
                {
                    'repeat': {
                        'child': {
                            'order': {},
                        },
                        'times': 2,
                        'every_trading_day_at': '09:20',
                    },
                },
                [],
                FROZEN_NOW.replace(day=24, hour=9, minute=20).timestamp(),
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_repeat_every_trading_day_sends_its_second_copy_the_morning_after',
                {
                    'repeat': {
                        'child': {
                            'order': {},
                        },
                        'times': 2,
                        'every_trading_day_at': '09:20',
                    },
                },
                [],
                FROZEN_NOW.replace(day=25, hour=9, minute=20).timestamp(),
                accepted,
            ),
            self.plan_clock_result(
                'a_plan_repeat_every_trading_day_taken_before_its_time_starts_that_day',
                {
                    'repeat': {
                        'child': {
                            'order': {},
                        },
                        'times': 2,
                        'every_trading_day_at': '09:20',
                    },
                },
                [],
                FROZEN_NOW.replace(hour=9, minute=20).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=9, minute=0),
            ),
            self.plan_clock_result(
                'a_plan_repeat_with_two_schedules_is_refused',
                {
                    'repeat': {
                        'child': {
                            'order': {},
                        },
                        'times': 2,
                        'every_minutes': 5,
                        'every_trading_day_at': '09:20',
                    },
                },
                [],
                frozen + 60,
                accepted,
            ),
        ]

    def run_plan_fill_follower_checks(self):
        """Runs plans whose second order follows the first's fills: a hedge in whole lots, a legged spread, and a two-sided breakout's exits, beside the types they stand for.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        steady = self.book_at(1000.00, 1000.05)
        numbered = dict(
            accepted,
            number_orders=True,
        )
        breakout = {
            'order': {
                'presets': [
                    {
                        'two_sided_breakout': {
                            'buy_trigger': 1010,
                            'buy_limit': 1012,
                            'sell_trigger': 990,
                            'sell_limit': 988,
                            'stop_distance': 25,
                            'stop_limit_offset': 2,
                        },
                    },
                ],
            },
        }
        spread = {
            'order': {
                'presets': [
                    {
                        'legged_spread': {
                            'net_price': 20,
                            'candidates': [
                                {
                                    'instrument_id': identifiers['reliance'],
                                    'transaction_type': 'BUY',
                                    'quantity': 500,
                                    'price': 1000,
                                },
                                {
                                    'instrument_id': identifiers['reliance_future'],
                                    'transaction_type': 'SELL',
                                    'quantity': 500,
                                    'price': 980,
                                },
                            ],
                        },
                    },
                ],
            },
        }
        return [
            self.plan_price_result(
                'a_plan_attached_hedge_sells_the_future_in_whole_lots_as_the_entry_fills',
                {
                    'order': {
                        'presets': [
                            {
                                'attached_hedge': {
                                    'hedge_instrument_id': identifiers['reliance_future'],
                                    'ratio': 1,
                                },
                            },
                        ],
                    },
                },
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.scenarios.quote(),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'OPEN', 600),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 1000),
                        ],
                    },
                ],
                accepted,
                body_overrides={
                    'quantity': 1000,
                },
            ),
            self.plan_price_result(
                'a_plan_attached_hedge_sized_by_delta_sells_about_half_a_bought_call',
                {
                    'order': {
                        'presets': [
                            {
                                'attached_hedge': {
                                    'hedge_instrument_id': identifiers['reliance_future'],
                                    'delta_volatility': 12.5,
                                },
                            },
                        ],
                    },
                },
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.scenarios.quote(last_price=25000),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 1500),
                        ],
                    },
                ],
                accepted,
                body_overrides={
                    'instrument_id': identifiers['nifty_option'],
                    'quantity': 1500,
                    'price': 160,
                },
            ),
            self.plan_price_result(
                'a_plan_attached_hedge_sized_by_delta_buys_the_future_against_a_bought_put',
                {
                    'order': {
                        'presets': [
                            {
                                'attached_hedge': {
                                    'hedge_instrument_id': identifiers['reliance_future'],
                                    'delta_volatility': 12.5,
                                },
                            },
                        ],
                    },
                },
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.scenarios.quote(last_price=82000),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 2000),
                        ],
                    },
                ],
                accepted,
                body_overrides={
                    'instrument_id': identifiers['sensex_option'],
                    'quantity': 2000,
                    'price': 160,
                },
            ),
            self.plan_price_result(
                'a_plan_attached_hedge_with_both_a_ratio_and_a_delta_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'attached_hedge': {
                                    'hedge_instrument_id': identifiers['reliance_future'],
                                    'ratio': 1,
                                    'delta_volatility': 12.5,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_price_result(
                'a_plan_attached_hedge_sized_by_delta_on_a_stock_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'attached_hedge': {
                                    'hedge_instrument_id': identifiers['reliance_future'],
                                    'delta_volatility': 12.5,
                                },
                            },
                        ],
                    },
                },
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.plan_result(
                'a_plan_legged_spread_prices_its_second_leg_from_the_first_fill',
                spread,
                [
                    self.update('26091500000021', 'COMPLETE', 500, average_price=1002.0),
                ],
                accepted,
            ),
            self.plan_result(
                'a_plan_two_sided_breakout_cancels_the_side_that_did_not_fire',
                breakout,
                [
                    self.update('26091500000101', 'OPEN', 10, average_price=1010.0),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_two_sided_breakout_that_breaks_down_protects_the_short',
                breakout,
                [
                    self.update('26091500000102', 'OPEN', 10, average_price=990.0),
                ],
                numbered,
            ),
            self.plan_result(
                'a_plan_legged_spread_with_three_legs_is_refused',
                {
                    'order': {
                        'presets': [
                            {
                                'legged_spread': {
                                    'net_price': 20,
                                    'candidates': [
                                        {'instrument_id': identifiers['reliance']},
                                        {'instrument_id': identifiers['kwil']},
                                        {'instrument_id': identifiers['nifty_option']},
                                    ],
                                },
                            },
                        ],
                    },
                },
                [],
                accepted,
            ),
        ]

    def run_reaction_checks(self):
        """Runs the linked order types through a fill, which is the only way they do anything.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        bracket_body = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
            synthetic={
                'type': 'bracket',
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_price': 1010,
            },
        )
        return [
            self.reaction_result(
                'a_bracket_arms_its_exits_on_the_first_partial_fill',
                bracket_body,
                [
                    self.update('26091500000021', 'OPEN', 4),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_bracket_grows_its_exits_as_the_entry_fills_further',
                bracket_body,
                [
                    self.update('26091500000021', 'OPEN', 4),
                    self.update('26091500000021', 'COMPLETE', 10),
                ],
                accepted,
            ),
            self.reaction_result(
                'an_oco_reduces_the_sibling_rather_than_cancelling_it',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'oco',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                        'target_price': 1010,
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 4),
                ],
                accepted,
                positions=10,
            ),
            self.reaction_result(
                'an_oco_takes_only_the_new_part_of_a_second_fill_off_the_sibling',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'oco',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                        'target_price': 1010,
                    },
                ),
                [
                    self.update('26091500000101', 'OPEN', 0),
                    self.update('26091500000102', 'OPEN', 3),
                    self.update('26091500000102', 'OPEN', 7),
                ],
                dict(accepted, number_orders=True),
                positions=10,
            ),
            self.reaction_result(
                'a_scale_out_takes_only_the_new_part_of_a_targets_second_fill_off_the_stop',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'scale_out',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                        'target_prices': [
                            1010,
                            1020,
                        ],
                    },
                ),
                [
                    self.update('26091500000101', 'COMPLETE', 10),
                    self.update('26091500000102', 'OPEN', 0),
                    self.update('26091500000103', 'OPEN', 2),
                    self.update('26091500000103', 'OPEN', 4),
                ],
                dict(accepted, number_orders=True),
            ),
            self.reaction_result(
                'the_rate_budget_now_covers_changes_not_only_placements',
                bracket_body,
                [
                    self.update('26091500000021', 'OPEN', 4),
                    self.update('26091500000021', 'COMPLETE', 10),
                ],
                accepted,
                gated=3,
            ),
            self.reaction_result(
                'a_legged_spread_prices_its_second_leg_from_the_first_fill',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'legged_spread',
                        'net_price': 20,
                        'candidates': [
                            {
                                'instrument_id': identifiers['reliance'],
                                'transaction_type': 'BUY',
                                'quantity': 500,
                                'price': 1000,
                            },
                            {
                                'instrument_id': (
                                    identifiers['reliance_future']
                                ),
                                'transaction_type': 'SELL',
                                'quantity': 500,
                                'price': 980,
                            },
                        ],
                    },
                ),
                [
                    self.update('26091500000021', 'COMPLETE', 500,
                                average_price=1002.0),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_legged_spread_with_three_legs_is_refused',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'legged_spread',
                        'net_price': 20,
                        'candidates': [
                            {'instrument_id': identifiers['reliance']},
                            {'instrument_id': identifiers['kwil']},
                            {'instrument_id': identifiers['nifty_option']},
                        ],
                    },
                ),
                [],
                accepted,
            ),
            self.reaction_result(
                'a_basket_places_every_leg_and_reports_each_one',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'basket',
                        'candidates': [
                            {
                                'instrument_id': identifiers['reliance'],
                                'quantity': 10,
                                'price': 1000,
                            },
                            {
                                'instrument_id': identifiers['kwil'],
                                'quantity': 5,
                                'price': 250,
                            },
                            {
                                'instrument_id': identifiers['nifty_option'],
                                'transaction_type': 'SELL',
                                'quantity': 75,
                                'price': 120,
                            },
                        ],
                    },
                ),
                [],
                accepted,
            ),
            self.reaction_result(
                'a_basket_that_repeats_an_instrument_is_refused',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'basket',
                        'candidates': [
                            {
                                'instrument_id': identifiers['reliance'],
                                'quantity': 10,
                            },
                            {
                                'instrument_id': identifiers['reliance'],
                                'quantity': 5,
                            },
                        ],
                    },
                ),
                [],
                accepted,
            ),
            self.reaction_result(
                'a_one_cancels_all_group_calls_off_the_rest_on_the_first_fill',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'oca',
                        'candidates': [
                            {
                                'instrument_id': identifiers['reliance'],
                                'quantity': 10,
                                'price': 1000,
                            },
                            {
                                'instrument_id': identifiers['kwil'],
                                'quantity': 5,
                                'price': 250,
                            },
                            {
                                'instrument_id': identifiers['sensex_option'],
                                'quantity': 20,
                                'price': 80,
                            },
                        ],
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 4),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_cover_order_arms_its_stop_and_has_no_target',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'cover',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 4),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_cover_order_with_a_target_is_refused',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'cover',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                        'target_price': 1010,
                    },
                ),
                [],
                accepted,
            ),
            self.reaction_result(
                'an_iceberg_shows_the_next_slice_only_once_the_last_one_filled',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=100,
                    synthetic={
                        'type': 'iceberg',
                        'slice_quantity': 20,
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 12),
                    self.update('26091500000021', 'COMPLETE', 20),
                ],
                accepted,
            ),
            self.reaction_result(
                'an_iceberg_varies_what_it_shows_when_asked_to',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=100,
                    synthetic={
                        'type': 'iceberg',
                        'slice_quantity': 20,
                        'randomise_percent': 25,
                    },
                ),
                [
                    self.update('26091500000021', 'COMPLETE', 20),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_grid_replaces_a_filled_rung_with_its_opposite',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=5,
                    synthetic={
                        'type': 'grid',
                        'levels': 2,
                        'step_points': 5,
                        'most_inventory': 20,
                    },
                ),
                [
                    self.update('26091500000021', 'COMPLETE', 5),
                ],
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.reaction_result(
                'a_grid_stops_adding_to_a_side_once_it_hits_its_cap',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=5,
                    synthetic={
                        'type': 'grid',
                        'levels': 2,
                        'step_points': 5,
                        'most_inventory': 5,
                    },
                ),
                [
                    self.update('26091500000021', 'COMPLETE', 5),
                ],
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.reaction_result(
                'a_grid_without_an_inventory_cap_is_refused',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=5,
                    synthetic={
                        'type': 'grid',
                        'levels': 2,
                        'step_points': 5,
                    },
                ),
                [],
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.reaction_result(
                'a_scale_out_arms_one_stop_and_several_targets',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=9,
                    synthetic={
                        'type': 'scale_out',
                        'stop_price': 990,
                        'stop_limit_price': 988,
                        'target_prices': [1010, 1020, 1030],
                    },
                ),
                [
                    self.update('26091500000021', 'COMPLETE', 9),
                ],
                accepted,
            ),
            self.reaction_result(
                'a_two_sided_breakout_cancels_the_side_that_did_not_fire',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'two_sided_breakout',
                        'buy_trigger': 1010,
                        'buy_limit': 1012,
                        'sell_trigger': 990,
                        'sell_limit': 988,
                        'stop_distance': 25,
                        'stop_limit_offset': 2,
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 10, average_price=1010.0),
                ],
                accepted,
            ),
            self.reaction_result(
                'an_oto_places_its_child_sized_to_what_actually_filled',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    order_type='LIMIT',
                    price=1000,
                    quantity=10,
                    synthetic={
                        'type': 'oto',
                        'then': {
                            'transaction_type': 'SELL',
                            'order_type': 'LIMIT',
                            'price': 1010,
                        },
                    },
                ),
                [
                    self.update('26091500000021', 'OPEN', 6),
                ],
                accepted,
            ),
        ]

    def priced_clock_result(self, name, request_body, quote):
        """Places one timed order against a quote and records the price of every leg it placed.

        Args:
            name (str): The check's name.
            request_body (dict): The request body.
            quote (dict): The live quote to seed.

        Returns:
            dict: The recorded result, with `leg_prices`.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        result = self.clock_result(
            name,
            request_body,
            [],
            FROZEN_NOW.timestamp() + 60,
            accepted,
            quote=quote,
        )
        prices = []
        for document in self.fake_redis.hashes.get('unified:orders:parents', {}).values():
            for leg in ParentOrder.from_document(json.loads(document)).legs:
                prices.append(leg.price)
        result['leg_prices'] = prices
        return result

    def clock_result(
        self,
        name,
        request_body,
        fills,
        tick_at,
        answer=None,
        quote=None,
        positions=None,
        resting=None,
        taken_at=None,
        resting_status='OPEN',
        position_product='MIS',
    ):
        """Places one timed order, optionally fills it, then gives it a clock tick.

        The tick is called with a chosen moment rather than waited for, so a scenario about half past ten costs no time and means the same thing on every run. A second tick follows, to check the type does not act twice on one instruction.

        Args:
            name (str): The check's name.
            request_body (dict): The request body.
            fills (list): Order updates to apply before the tick.
            tick_at (float): The Unix time to tick at.
            answer (dict | None): The stubbed broker answer.
            quote (dict | None): A live quote to seed, for a type that reads the book when it is placed.
            positions (float | None): A net position in RELIANCE to seed, for a type that reads the account's holdings.
            resting (list | None): Flattrade order ids of open RELIANCE orders placed outside the engine, for a type that cancels what is resting.
            taken_at (datetime.datetime | None): The moment the engine takes the order, or None for `FROZEN_NOW`.
            resting_status (str): The status the order feed holds the resting orders in, such as `PENDING` for a stop waiting for its trigger.
            position_product (str): The product the seeded positions are held on, such as `NRML`.

        Returns:
            dict: The recorded result.
        """
        taken_at = taken_at or FROZEN_NOW
        settings = {
            'answer': answer,
        }
        if request_body.get('instrument_id'):
            settings['instrument_id'] = request_body['instrument_id']
        scenario = self.scenarios.intents(name, [request_body], **settings)
        self.fake_redis = self.build_state()
        if quote is not None:
            self.seed_quote(quote)
        if positions is not None:
            self.seed_positions(positions, position_product)
        self.seed_resting(resting, resting_status)
        self.network.reset(answer)
        self.counting_uuid.reset()
        original_time = time.time
        time.time = lambda: taken_at.timestamp()
        try:
            reply_keys = self.write_intents(scenario)
        finally:
            time.time = original_time

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        event_log = engine_stand_ins.RecordingEventLog()
        parent_store = ParentStore(self.fake_redis)
        ticker = ClockTicker(parent_store, event_log, placement, logger, None)
        engine = OrderEngine(
            self.fake_redis,
            placement,
            EngineLock(self.fake_redis, logger),
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            parent_store,
        )
        # The whole check runs on one frozen clock, so a slice due five minutes in is due five
        # minutes after the order was recorded rather than five minutes after the real time of day.
        original_time = time.time
        original_now = moments.Moments.now
        time.time = lambda: taken_at.timestamp()
        moments.Moments.now = lambda self: taken_at
        try:
            engine.run(engine_stand_ins.OnePassStop(3))
        finally:
            time.time = original_time
            moments.Moments.now = original_now
        reply = self.shown_replies(reply_keys)[0]

        follower = OrderUpdateFollower(
            parent_store,
            event_log,
            logger,
            None,
            placement,
        )
        for update in fills:
            book = self.fake_redis.hashes.setdefault(
                'flattrade:orders:orders',
                {},
            )
            book[str(update['order_id'])] = self.broker_book_entry(
                str(update['order_id']),
                status=update.get('status', 'OPEN'),
            )
            changed = follower.follow({
                'update': json.dumps(update),
            })
            if changed is not None:
                parent_store.save(changed)

        before = len(self.network.sent_requests)
        acted = self.tick_at(ticker, tick_at)
        after_first = len(self.network.sent_requests)
        self.tick_at(ticker, tick_at + 60)

        parents = [
            ParentOrder.from_document(json.loads(one))
            for one in self.fake_redis.hashes.get(
                'unified:orders:parents',
                {},
            ).values()
        ]
        result = {
            'name': name,
            'reply': reply,
            'sent_before_tick': before,
            'sent_after_tick': after_first,
            'sent_after_second_tick': len(self.network.sent_requests),
            'acted': acted,
            'requests': [
                request['url'].rsplit('/', 1)[-1]
                for request in self.network.sent_requests
            ],
            'legs': [
                {
                    'role': leg.role,
                    'state': leg.state,
                    'quantity': leg.quantity,
                }
                for parent in parents
                for leg in parent.legs
            ],
            'parent_states': [parent.state for parent in parents],
        }
        if resting is not None:
            result['outside_cancels'] = [
                {
                    'event': event['event'],
                    'broker': event.get('broker'),
                    'broker_order_id': event.get('broker_order_id'),
                    'outcome': event.get('outcome'),
                }
                for event in event_log.events
                if event['event'].startswith('outside_cancel')
            ]
        return result

    def restart_parents(self, event_log, parent_store):
        """Rebuilds every parent from its recorded events alone, which is all an engine restart has.

        Args:
            event_log (engine_stand_ins.RecordingEventLog): The recorded events.
            parent_store (ParentStore): The Redis copy to replace.

        Returns:
            None: This method returns nothing.
        """
        by_parent = {}
        for event in event_log.read_since(None):
            parent_order_id = str(event.get('parent_order_id'))
            by_parent.setdefault(parent_order_id, []).append(event)
        parents = []
        for events in by_parent.values():
            parent = ParentOrder.from_events(events)
            if parent is not None:
                parents.append(parent)
        parent_store.rebuild(parents)

    def seed_quote(self, quote):
        """Puts one live quote where the engine and the price ticker both read it.

        Args:
            quote (dict | None): The quote, or None to leave the instrument without one.

        Returns:
            None: This method returns nothing.
        """
        instrument_id = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[
            'reliance'
        ]
        quotes = self.fake_redis.hashes.setdefault('unified:quotes:live', {})
        if quote is None:
            quotes.pop(instrument_id, None)
            return
        quotes[instrument_id] = json.dumps(quote)

    def seed_resting(self, resting, status='OPEN'):
        """Puts open RELIANCE orders placed outside the engine where the order updates and the broker's book hold them.

        Args:
            resting (list | None): Flattrade order ids, or objects with `order_id` and the `product` the update records.
            status (str): The status the order feed holds them in, on the shared vocabulary.

        Returns:
            None: This method returns nothing.
        """
        for item in resting or []:
            product = None
            if isinstance(item, dict):
                order_id = item['order_id']
                product = item.get('product')
            else:
                order_id = item
            update = {
                'broker': 'flattrade',
                'order_id': order_id,
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'status': status,
            }
            if product is not None:
                update['product'] = product
            self.fake_redis.hashes.setdefault('unified:order-updates', {})[
                f'flattrade:{order_id}'
            ] = json.dumps(update)
            self.fake_redis.hashes.setdefault('flattrade:orders:orders', {})[
                order_id
            ] = self.broker_book_entry(order_id)

    def seed_other_quotes(self, step):
        """Puts the quotes a step carries for instruments other than RELIANCE, such as an underlying.

        Args:
            step (dict): The step, whose `other_quotes` maps an instrument's name in `INSTRUMENT_IDENTIFIERS` to its quote.

        Returns:
            None: This method returns nothing.
        """
        quotes = self.fake_redis.hashes.setdefault('unified:quotes:live', {})
        for name, quote in (step.get('other_quotes') or {}).items():
            instrument_id = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS[name]
            quotes[instrument_id] = json.dumps(quote)

    def price_result(
        self,
        name,
        request_body,
        steps,
        answer=None,
        throttle_seconds=0,
        book_overrides=None,
        fills=None,
        positions=None,
        restart_between_ticks=False,
        daily_caps=None,
        daily_sent=None,
        resting=None,
        book_every_order=False,
    ):
        """Places one watching order, then walks it through a sequence of quotes.

        Each step is a quote and the moment it arrives at, so a scenario about a chaser stepping every five seconds costs no time and means the same thing on every run. Every broker request is kept in the order it was sent, which is what shows whether a type moved its order once, twice or not at all.

        Args:
            name (str): The check's name.
            request_body (dict): The request body.
            steps (list): One `{"quote": dict | None, "at": float}` per tick, where `at` is seconds after the order was placed, and optionally `other_quotes` for other instruments, `updates`, order updates applied before the tick, `funds`, the combined funds document, and a caller's change or cancel run through the engine's commands before the tick: `held_change` and `part_cancel` name a parent's part, `leg_change` and `leg_cancel` one of its broker orders. `restart: True` rebuilds every parent from its recorded events after that tick, as one engine restart does.
            answer (dict | None): The stubbed broker answer.
            throttle_seconds (float): The shortest gap the re-pricing throttle allows between two moves of one order.
            book_overrides (dict | None): Fields to replace on the broker's order book entry, for a type whose order is not a plain limit.
            fills (list | None): Order updates to apply before the first tick, for a type that only acts once its legs are filled.
            positions (float | None): A net position in RELIANCE to seed, for a type that reads the account's holdings.
            restart_between_ticks (bool): Whether to rebuild every parent from its recorded events after every tick, as an engine restart does.
            daily_caps (dict | None): Each capped broker's daily cap, or None for no daily order count.
            daily_sent (dict | None): Each broker's order messages already sent today, written before the order is placed.
            resting (list | None): Flattrade order ids of open RELIANCE orders placed outside the engine, for a type that cancels what is resting.
            book_every_order (bool): Whether every order placed on a tick is also put into the broker's book before the next tick, so the order type can change or cancel it, as it can in life.

        Returns:
            dict: The recorded result.
        """
        settings = {
            'answer': answer,
        }
        if request_body.get('instrument_id'):
            settings['instrument_id'] = request_body['instrument_id']
        scenario = self.scenarios.intents(name, [request_body], **settings)
        self.fake_redis = self.build_state()
        self.network.reset(answer)
        self.counting_uuid.reset()
        starting = steps[0]['quote'] if steps else None
        self.seed_quote(starting)
        if steps:
            self.seed_other_quotes(steps[0])
        self.seed_resting(resting)
        if positions is not None:
            self.seed_positions(positions)
        reply_keys = self.write_intents(scenario)

        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        event_log = engine_stand_ins.RecordingEventLog()
        parent_store = ParentStore(self.fake_redis)
        gates = RiskGates(
            RateBudget(self.fake_redis, 100, 100, 0, logger),
            LossLockout(self.fake_redis, 0, logger),
            OrderToTradeRatio(),
            RepricingThrottle(throttle_seconds),
            self.build_daily_count(
                {
                    'daily_caps': daily_caps,
                    'daily_sent': daily_sent,
                },
                logger,
            ),
        )
        placement.order_placement.attach_daily_count(gates.daily_count)
        ticker = PriceTicker(
            self.fake_redis,
            parent_store,
            event_log,
            placement,
            logger,
            gates,
        )
        engine = OrderEngine(
            self.fake_redis,
            placement,
            EngineLock(self.fake_redis, logger),
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            parent_store,
            None,
            gates,
        )
        started = FROZEN_NOW.timestamp()
        original_time = time.time
        time.time = lambda: started
        try:
            engine.run(engine_stand_ins.OnePassStop(3))
        finally:
            time.time = original_time
        reply = self.shown_replies(reply_keys)[0]

        # The broker's own book has to hold the order before a change can be built from it, exactly
        # as it does in life.
        book = self.fake_redis.hashes.setdefault('flattrade:orders:orders', {})
        book['26091500000021'] = self.broker_book_entry(
            '26091500000021',
            status='OPEN',
            **(book_overrides or {}),
        )
        for number in range(1, self.network.placed + 1):
            numbered = str(26091500000100 + number)
            book[numbered] = self.broker_book_entry(
                numbered,
                status='OPEN',
                **(book_overrides or {}),
            )

        follower = OrderUpdateFollower(
            parent_store,
            event_log,
            logger,
            gates,
            placement,
        )
        for update in fills or []:
            changed = follower.follow({
                'update': json.dumps(update),
            })
            if changed is not None:
                parent_store.save(changed)

        moves = []
        held_changes = []
        leg_changes = []
        part_cancels = []
        for step in steps:
            step_at = started + step.get('at', 0)
            time.time = lambda: step_at
            try:
                if book_every_order:
                    for number in range(1, self.network.placed + 1):
                        numbered = str(26091500000100 + number)
                        if numbered not in book:
                            book[numbered] = self.broker_book_entry(
                                numbered,
                                status='OPEN',
                                **(book_overrides or {}),
                            )
                self.seed_quote(step.get('quote'))
                self.seed_other_quotes(step)
                if step.get('funds') is not None:
                    self.fake_redis.strings['unified:portfolio:funds'] = json.dumps(step['funds'])
                for update in step.get('updates') or []:
                    changed = follower.follow({
                        'update': json.dumps(update),
                    })
                    if changed is not None:
                        parent_store.save(changed)
                if step.get('estimate') is not None:
                    self.seed_estimate(step['estimate'])
                if step.get('held_change') is not None:
                    commands = ParentCommands(
                        placement,
                        event_log,
                        parent_store,
                        logger,
                        gates,
                    )
                    arguments = dict(step['held_change'])
                    for parent_order_id in self.fake_redis.hashes.get('unified:orders:parents', {}):
                        arguments['parent_id'] = parent_order_id
                    try:
                        answer_body, status = commands.modify_held(arguments)
                    except RefusedRequestError as refusal:
                        answer_body, status = refusal.body, refusal.status
                    shown_change = {
                        'status': status,
                        'error': answer_body.get('error'),
                        'price': answer_body.get('price'),
                        'quantity': answer_body.get('quantity'),
                    }
                    if step['held_change'].get('part') is not None:
                        shown_change['part'] = answer_body.get('part')
                        shown_change['trigger_price'] = answer_body.get('trigger_price')
                        shown_change['orders'] = answer_body.get('orders')
                    held_changes.append(shown_change)
                if step.get('part_cancel') is not None:
                    commands = ParentCommands(
                        placement,
                        event_log,
                        parent_store,
                        logger,
                        gates,
                    )
                    arguments = dict(step['part_cancel'])
                    for parent_order_id in self.fake_redis.hashes.get('unified:orders:parents', {}):
                        arguments['parent_id'] = parent_order_id
                    try:
                        answer_body, status = commands.cancel_parent(arguments)
                    except RefusedRequestError as refusal:
                        answer_body, status = refusal.body, refusal.status
                    part_cancels.append({
                        'status': status,
                        'error': answer_body.get('error'),
                        'outcome': answer_body.get('outcome'),
                        'state': answer_body.get('state'),
                        'orders': answer_body.get('orders'),
                        'resting_legs': answer_body.get('resting_legs'),
                        'status_message': answer_body.get('status_message'),
                    })
                if step.get('leg_cancel') is not None:
                    commands = ParentCommands(
                        placement,
                        event_log,
                        parent_store,
                        logger,
                        gates,
                    )
                    arguments = {
                        'broker': 'flattrade',
                        'order_id': step['leg_cancel'],
                    }
                    for parent_order_id in self.fake_redis.hashes.get('unified:orders:parents', {}):
                        arguments['parent_id'] = parent_order_id
                    try:
                        answer_body, status = commands.cancel_leg(arguments)
                    except RefusedRequestError as refusal:
                        answer_body, status = refusal.body, refusal.status
                    leg_changes.append({
                        'status': status,
                        'error': answer_body.get('error'),
                        'outcome': answer_body.get('outcome'),
                    })
                if step.get('leg_change') is not None:
                    commands = ParentCommands(
                        placement,
                        event_log,
                        parent_store,
                        logger,
                        gates,
                    )
                    arguments = {
                        'broker': 'flattrade',
                        'quantity': None,
                        'quantity_units': None,
                        'price': None,
                        'trigger_price': None,
                    }
                    arguments.update(step['leg_change'])
                    if arguments['quantity'] is not None:
                        arguments['quantity_units'] = arguments['quantity']
                    for parent_order_id in self.fake_redis.hashes.get('unified:orders:parents', {}):
                        arguments['parent_id'] = parent_order_id
                    try:
                        answer_body, status = commands.modify_leg(arguments)
                    except RefusedRequestError as refusal:
                        answer_body, status = refusal.body, refusal.status
                    leg_changes.append({
                        'status': status,
                        'error': answer_body.get('error'),
                        'outcome': answer_body.get('outcome'),
                    })
                before = len(self.network.sent_requests)
                self.tick_at(ticker, step_at)
                moves.append(len(self.network.sent_requests) - before)
                if restart_between_ticks or step.get('restart'):
                    self.restart_parents(event_log, parent_store)
            finally:
                time.time = original_time

        parents = [
            ParentOrder.from_document(json.loads(one))
            for one in self.fake_redis.hashes.get(
                'unified:orders:parents',
                {},
            ).values()
        ]
        result = {
            'name': name,
            'reply': reply,
            'requests': [
                request['url'].rsplit('/', 1)[-1]
                for request in self.network.sent_requests
            ],
            'moves_per_tick': moves,
            'legs': [
                {
                    'role': leg.role,
                    'state': leg.state,
                    'quantity': leg.quantity,
                    'price': leg.price,
                }
                for parent in parents
                for leg in parent.legs
            ],
            'parent_states': [parent.state for parent in parents],
            'repricing': gates.throttle.counts(),
        }
        if daily_caps is not None:
            result['daily_counts'] = self.shown_daily_counts()
        synthetic = request_body.get('synthetic') or {}
        if synthetic.get('type') == 'virtual_limit' or '"virtual_limit"' in json.dumps(synthetic):
            result['held'] = [
                {
                    'paper_filled': parent.parameters.get('paper_filled'),
                    'missed_quantity': parent.parameters.get('missed_quantity'),
                }
                for parent in parents
            ]
            result['paper_fills'] = [
                event.get('filled_quantity')
                for event in event_log.events
                if event.get('event') == 'paper_filled'
            ]
        if held_changes:
            result['held_changes'] = held_changes
        if leg_changes:
            result['leg_changes'] = leg_changes
        if part_cancels:
            result['part_cancels'] = part_cancels
        return result

    def seed_estimate(self, estimate):
        """Writes a queue estimate for every parent, every part of a plan and every rung of a scale with profit-taker, as `bin/unified/orders/virtual_book` would.

        Args:
            estimate (dict): The estimate's fields.

        Returns:
            None: This method returns nothing.
        """
        estimates = self.fake_redis.hashes.setdefault(ESTIMATES_KEY, {})
        stored = self.fake_redis.hashes.get('unified:orders:parents', {})
        for parent_order_id, document in stored.items():
            estimates[parent_order_id] = json.dumps(estimate)
            parts = (json.loads(document).get('parameters') or {}).get('parts') or {}
            for path, record in parts.items():
                estimates[VirtualBook.part_key(parent_order_id, path)] = json.dumps(estimate)
                rungs = ((record or {}).get('own_memory') or {}).get('rungs') or []
                for index, rung in enumerate(rungs):
                    rung_key = VirtualBook.part_key(parent_order_id, VirtualBook.rung_path(path, index, rung.get('cycles') or 0))
                    estimates[rung_key] = json.dumps(estimate)

    def tick_at(self, ticker, moment):
        """Runs one tick as though it were `moment`.

        Args:
            ticker (ClockTicker | PriceTicker): The ticker.
            moment (float): The Unix time to tick at.

        Returns:
            int: How many parents acted.
        """
        original = time.time
        time.time = lambda: moment
        try:
            return ticker.tick()
        finally:
            time.time = original

    def days_result(self, name, request_body, steps, positions=None):
        """Places one timed order at 08:45 on `FROZEN_NOW`'s day, then gives it one clock tick per step, each at its own moment and after its own order updates.

        Args:
            name (str): The check's name.
            request_body (dict): The request body.
            steps (list): One `{"at": datetime.datetime, "quote": dict | None, "updates": list | None}` per tick.
            positions (float | None): A net position in RELIANCE to seed, for a plan that reads it.

        Returns:
            dict: The recorded result, with what each tick sent and the parent's state after it.
        """
        answer = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        taken_at = FROZEN_NOW.replace(hour=8, minute=45)
        scenario = self.scenarios.intents(name, [request_body], answer=answer)
        self.fake_redis = self.build_state()
        self.seed_quote(self.scenarios.quote())
        if positions is not None:
            self.seed_positions(positions)
        self.network.reset(answer)
        self.counting_uuid.reset()
        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        event_log = engine_stand_ins.RecordingEventLog()
        parent_store = ParentStore(self.fake_redis)
        ticker = ClockTicker(parent_store, event_log, placement, logger, None)
        engine = OrderEngine(
            self.fake_redis,
            placement,
            EngineLock(self.fake_redis, logger),
            logger,
            STALE_INTENT_SECONDS,
            RESULT_TTL_SECONDS,
            event_log,
            parent_store,
        )
        original_time = time.time
        original_now = moments.Moments.now
        time.time = lambda: taken_at.timestamp()
        moments.Moments.now = lambda self: taken_at
        try:
            reply_keys = self.write_intents(scenario)
            engine.run(engine_stand_ins.OnePassStop(3))
        finally:
            time.time = original_time
        follower = OrderUpdateFollower(parent_store, event_log, logger, None, placement)
        ticks = []
        try:
            for step in steps:
                moment = step['at']
                moments.Moments.now = lambda self, moment=moment: moment
                if step.get('quote') is not None:
                    self.seed_quote(step['quote'])
                for update in step.get('updates') or []:
                    book = self.fake_redis.hashes.setdefault('flattrade:orders:orders', {})
                    book[str(update['order_id'])] = self.broker_book_entry(
                        str(update['order_id']),
                        status=update['status'],
                    )
                    changed = follower.follow({
                        'update': json.dumps(update),
                    })
                    if changed is not None:
                        parent_store.save(changed)
                before = len(self.network.sent_requests)
                self.tick_at(ticker, moment.timestamp())
                sent = []
                for request in self.network.sent_requests[before:]:
                    sent.append({
                        'url': request['url'].rsplit('/', 1)[-1],
                        'quantity': self.sent_quantity(request),
                    })
                stored = self.fake_redis.hashes.get('unified:orders:parents', {})
                states = []
                for document in stored.values():
                    states.append(json.loads(document).get('state'))
                ticks.append({
                    'at': moment.isoformat(),
                    'sent': sent,
                    'parent_states': states,
                })
        finally:
            moments.Moments.now = original_now
        return {
            'name': name,
            'reply': self.shown_replies(reply_keys)[0],
            'ticks': ticks,
        }

    def run_closed_position_checks(self):
        """Runs the types that must stop once the position they protect has closed: a hidden stop whose backstop filled or could not be cancelled, and a daily stop whose stop traded.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        steady = self.book_at(1000.00, 1000.05)
        touched = self.book_at(994.90, 995.20)
        hidden_stop = dict(entry, synthetic={
            'type': 'hidden_stop',
            'trigger_price': 995,
            'backstop_price': 990,
            'backstop_limit_price': 988,
        })
        results = [
            self.price_result(
                'a_hidden_stop_whose_backstop_filled_stops_watching',
                hidden_stop,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'updates': [self.update('26091500000021', 'COMPLETE', 10)]},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
                positions=10,
            ),
        ]
        original_cancel = EnginePlacement.cancel
        EnginePlacement.cancel = self.refused_cancel
        try:
            results.append(self.price_result(
                'a_hidden_stop_holds_its_exit_back_while_the_backstop_cannot_be_cancelled',
                hidden_stop,
                [
                    {'quote': steady, 'at': 0},
                    {'quote': touched, 'at': 1},
                    {'quote': touched, 'at': 2},
                ],
                accepted,
                positions=10,
            ))
        finally:
            EnginePlacement.cancel = original_cancel

        day_one_arm = FROZEN_NOW.replace(hour=9, minute=21)
        day_two_arm = day_one_arm.replace(day=day_one_arm.day + 1)
        stop_filled = self.update('26091500000021', 'COMPLETE', 10, average_price=988.0)
        still_below = self.scenarios.quote(
            last_price=985.00,
            depth={
                'buy': [
                    {'price': 985.00, 'quantity': 100, 'orders': 1},
                ],
                'sell': [
                    {'price': 985.05, 'quantity': 100, 'orders': 1},
                ],
            },
        )
        stop_settings = {
            'stop_price': 990,
            'stop_limit_price': 988,
            'arm_at': '09:20',
        }
        daily_stop = dict(entry, synthetic=dict(stop_settings, type='daily_stop'))
        plan_daily_stop = dict(entry, synthetic={
            'type': 'plan',
            'plan': {
                'order': {
                    'presets': [
                        {
                            'daily_stop': stop_settings,
                        },
                    ],
                },
            },
        })
        for label, quote in (
            ('above', self.scenarios.quote()),
            ('below', still_below),
        ):
            results.append(self.days_result(
                f'a_daily_stop_that_traded_places_nothing_the_next_morning_{label}_the_stop',
                daily_stop,
                [
                    {'at': day_one_arm},
                    {'at': day_one_arm.replace(hour=11), 'updates': [stop_filled]},
                    {'at': day_two_arm, 'quote': quote},
                ],
                positions=10,
            ))
        results.append(self.days_result(
            'a_plan_daily_stop_that_traded_places_nothing_the_next_morning_below_the_stop',
            plan_daily_stop,
            [
                {'at': day_one_arm},
                {'at': day_one_arm.replace(hour=11), 'updates': [stop_filled]},
                {'at': day_two_arm, 'quote': still_below},
            ],
            positions=10,
        ))
        return results

    @staticmethod
    def refused_cancel(placement, broker_name, broker_order_id):
        """Stands in for `EnginePlacement.cancel` at a broker that refuses every cancel.

        Args:
            placement (EnginePlacement): The placement, unused.
            broker_name (str): The broker.
            broker_order_id (str): The order, unused.

        Returns:
            None: Never returns.

        Raises:
            RefusedRequestError: Always, with HTTP 400.
        """
        del placement, broker_order_id
        raise RefusedRequestError.refusal(
            'the order is already complete and cannot be cancelled',
            400,
            broker=broker_name,
        )

    def run_late_auction_and_whole_lot_checks(self):
        """Runs an opening auction order whose engine was down past the pre-open, and a participation order on an instrument traded in lots, as the fixed type and as a plan.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        taken_early = FROZEN_NOW.replace(hour=8, minute=45)
        results = [
            self.clock_result(
                'an_opening_auction_order_is_cancelled_when_the_engine_missed_the_pre_open',
                dict(entry, synthetic={
                    'type': 'opening_auction',
                }),
                [],
                FROZEN_NOW.replace(hour=9, minute=30).timestamp(),
                accepted,
                taken_at=taken_early,
            ),
            self.plan_clock_result(
                'a_plan_opening_auction_order_is_cancelled_when_the_engine_missed_the_pre_open',
                {
                    'order': {
                        'presets': [
                            {
                                'opening_auction': {},
                            },
                        ],
                    },
                },
                [],
                FROZEN_NOW.replace(hour=9, minute=30).timestamp(),
                accepted,
                taken_at=taken_early,
            ),
        ]
        option = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option']
        steady = self.book_at(1000.00, 1000.05)
        steps = []
        for index, volume in enumerate((10000, 11000, 12000, 17500, 80000)):
            quote = dict(steady)
            quote['volume'] = volume
            steps.append({
                'quote': quote,
                'other_quotes': {
                    'nifty_option': quote,
                },
                'at': index,
            })
        results.append(self.price_result(
            'a_participation_order_sends_whole_lots_and_counts_only_what_it_sent',
            dict(entry, instrument_id=option, quantity=750, synthetic={
                'type': 'participation',
                'participation_percent': 10,
            }),
            steps,
            accepted,
        ))
        results.append(self.plan_price_result(
            'a_plan_participation_order_sends_whole_lots_across_a_restart',
            {
                'order': {
                    'presets': [
                        {
                            'participation': {
                                'participation_percent': 10,
                            },
                        },
                    ],
                },
            },
            steps,
            accepted,
            body_overrides={
                'instrument_id': option,
                'quantity': 750,
            },
            restart_between_ticks=True,
        ))
        return results

    def sent_terms(self):
        """The side, order type, prices and quantity of every broker request sent so far, read from Flattrade's form.

        Returns:
            list: One dict per request, holding the fields it carries.
        """
        shown = []
        for request in self.network.sent_requests:
            form = request.get('data') or ''
            terms = {
                'url': request['url'].rsplit('/', 1)[-1],
            }
            for name in ('trantype', 'prctyp', 'prc', 'trgprc', 'qty'):
                found = re.search(r'"%s": "([^"]*)"' % name, form)
                if found:
                    terms[name] = found.group(1)
            shown.append(terms)
        return shown

    def run_breakout_exit_checks(self):
        """Runs a two-sided breakout whose exits are distances from the fill, broken upwards and downwards, as the fixed type and as a plan, and the old absolute exits refused.

        Returns:
            list: One recorded result per check.
        """
        numbered = dict(
            self.scenarios.answers.json_answer(
                200,
                self.scenarios.answers.place_success('flattrade'),
            ),
            number_orders=True,
        )
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        settings = {
            'buy_trigger': 1010,
            'buy_limit': 1012,
            'sell_trigger': 990,
            'sell_limit': 988,
            'stop_distance': 25,
            'stop_limit_offset': 2,
            'target_distance': 20,
        }
        plan = {
            'order': {
                'presets': [
                    {
                        'two_sided_breakout': settings,
                    },
                ],
            },
        }
        results = []
        for direction, order_id, filled_at in (
            ('up', '26091500000101', 1010.0),
            ('down', '26091500000102', 990.0),
        ):
            result = self.plan_result(
                f'a_plan_two_sided_breakout_sets_its_exits_from_the_fill_when_it_breaks_{direction}',
                plan,
                [
                    self.update(order_id, 'COMPLETE', 10, average_price=filled_at),
                ],
                numbered,
            )
            result['terms'] = self.sent_terms()
            results.append(result)
        result = self.reaction_result(
            'a_two_sided_breakout_sets_its_exits_from_the_fill_when_it_breaks_down',
            self.scenarios.bodies.market_order(
                dry_run=None,
                order_type='LIMIT',
                price=1000,
                quantity=10,
                synthetic=dict(settings, type='two_sided_breakout'),
            ),
            [
                self.update('26091500000102', 'COMPLETE', 10, average_price=990.0),
            ],
            numbered,
        )
        result['terms'] = self.sent_terms()
        results.append(result)
        absolute = dict(settings)
        absolute.pop('stop_distance')
        absolute['stop_price'] = 985
        results.append(self.reaction_result(
            'a_two_sided_breakout_with_absolute_exits_is_refused',
            self.scenarios.bodies.market_order(
                dry_run=None,
                order_type='LIMIT',
                price=1000,
                quantity=10,
                synthetic=dict(absolute, type='two_sided_breakout'),
            ),
            [],
            accepted,
        ))
        results.append(self.plan_result(
            'a_plan_two_sided_breakout_with_absolute_exits_is_refused',
            {
                'order': {
                    'presets': [
                        {
                            'two_sided_breakout': absolute,
                        },
                    ],
                },
            },
            [],
            numbered,
        ))
        return results

    def run_clock_checks(self):
        """Runs the types that wait for a time of day rather than for a fill.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        frozen = FROZEN_NOW.timestamp()
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        return [
            self.clock_result(
                'a_scheduled_order_waits_for_its_time',
                dict(entry, synthetic={
                    'type': 'scheduled',
                    'at_time': '10:30',
                }),
                [],
                frozen + 60,
                accepted,
            ),
            self.clock_result(
                'a_scheduled_order_is_placed_once_its_time_comes',
                dict(entry, synthetic={
                    'type': 'scheduled',
                    'at_time': '10:30',
                }),
                [],
                frozen + 1900,
                accepted,
            ),
            self.clock_result(
                'a_good_till_time_order_is_cancelled_when_it_runs_out',
                dict(entry, synthetic={
                    'type': 'good_till_time',
                    'until_time': '10:30',
                }),
                [],
                frozen + 1900,
                accepted,
            ),
            self.clock_result(
                'a_limit_then_market_order_is_made_marketable_when_its_time_comes',
                dict(entry, synthetic={
                    'type': 'good_till_time',
                    'until_time': '10:30',
                    'at_expiry': 'market',
                }),
                [],
                frozen + 1900,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.clock_result(
                'an_opening_auction_order_waits_for_the_pre_open',
                dict(entry, synthetic={
                    'type': 'opening_auction',
                }),
                [],
                FROZEN_NOW.replace(hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
            ),
            self.clock_result(
                'an_opening_auction_order_during_collection_is_placed_at_once',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    synthetic={
                        'type': 'opening_auction',
                    },
                ),
                [],
                FROZEN_NOW.replace(hour=9, minute=3, second=1).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=9, minute=3),
            ),
            self.clock_result(
                'a_market_opening_auction_order_after_nine_oh_five_is_refused',
                self.scenarios.bodies.market_order(
                    dry_run=None,
                    synthetic={
                        'type': 'opening_auction',
                    },
                ),
                [],
                FROZEN_NOW.replace(hour=9, minute=6, second=1).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=9, minute=6),
            ),
            self.clock_result(
                'an_opening_auction_order_after_collection_is_refused',
                dict(entry, synthetic={
                    'type': 'opening_auction',
                }),
                [],
                frozen + 60,
                accepted,
            ),
            self.clock_result(
                'an_opening_auction_order_for_an_option_is_refused',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                    synthetic={
                        'type': 'opening_auction',
                    },
                ),
                [],
                FROZEN_NOW.replace(hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
            ),
            self.clock_result(
                'a_stop_order_cannot_join_the_opening_auction',
                dict(
                    entry,
                    order_type='SL',
                    trigger_price=990,
                    price=988,
                    synthetic={
                        'type': 'opening_auction',
                    },
                ),
                [],
                FROZEN_NOW.replace(hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
            ),
            self.clock_result(
                'a_futures_opening_auction_order_after_nine_oh_seven_is_refused',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance_future'],
                    synthetic={
                        'type': 'opening_auction',
                    },
                ),
                [],
                FROZEN_NOW.replace(hour=9, minute=8, second=1).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=9, minute=8),
            ),
            self.clock_result(
                'a_closing_price_order_waits_for_the_window_and_then_slices',
                dict(entry, quantity=60, synthetic={
                    'type': 'closing_price',
                }),
                [],
                FROZEN_NOW.replace(hour=15, minute=0).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=14, minute=30),
            ),
            self.clock_result(
                'a_closing_price_order_inside_the_window_starts_at_once',
                dict(entry, quantity=40, synthetic={
                    'type': 'closing_price',
                    'slices': 4,
                }),
                [],
                FROZEN_NOW.replace(hour=15, minute=15).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=15, minute=10),
            ),
            self.clock_result(
                'a_closing_price_order_after_the_close_is_refused',
                dict(entry, synthetic={
                    'type': 'closing_price',
                }),
                [],
                FROZEN_NOW.replace(hour=15, minute=32).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(hour=15, minute=31),
            ),
            self.clock_result(
                'a_closing_price_window_starting_after_the_close_is_refused',
                dict(entry, synthetic={
                    'type': 'closing_price',
                    'window_start': '15:40',
                }),
                [],
                frozen + 60,
                accepted,
            ),
            self.clock_result(
                'a_scheduled_order_taken_on_a_sunday_waits_through_sunday_afternoon',
                dict(entry, synthetic={'type': 'scheduled', 'at_time': '15:00'}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=15).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_scheduled_order_taken_on_a_sunday_is_placed_on_monday',
                dict(entry, synthetic={'type': 'scheduled', 'at_time': '15:00'}),
                [],
                FROZEN_NOW.replace(day=28, hour=15).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_scheduled_order_taken_on_a_holiday_friday_is_placed_the_next_monday',
                dict(entry, synthetic={'type': 'scheduled', 'at_time': '15:00'}),
                [],
                FROZEN_NOW.replace(month=10, day=5, hour=15).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(month=10, day=2),
            ),
            self.clock_result(
                'a_daily_stop_taken_on_a_sunday_places_nothing_that_day',
                dict(entry, synthetic={'type': 'daily_stop', 'stop_price': 990, 'stop_limit_price': 988, 'arm_at': '09:20'}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=9, minute=21).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27).replace(hour=8, minute=45),
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.clock_result(
                'a_daily_stop_taken_after_its_time_waits_for_the_next_trading_morning',
                dict(entry, synthetic={'type': 'daily_stop', 'stop_price': 990, 'stop_limit_price': 988, 'arm_at': '09:20'}),
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW,
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.clock_result(
                'a_closing_price_order_taken_on_a_sunday_is_scheduled_for_monday',
                dict(entry, synthetic={'type': 'closing_price'}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=15, minute=1).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'an_opening_auction_order_taken_on_a_sunday_joins_mondays_pre_open',
                dict(entry, synthetic={'type': 'opening_auction'}),
                [],
                FROZEN_NOW.replace(day=28, hour=9, minute=0, second=30).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_square_off_taken_on_a_sunday_is_scheduled_for_monday',
                dict(entry, synthetic={'type': 'square_off', 'at_time': '15:10', 'product': 'intraday'}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=15, minute=11).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_good_till_time_order_taken_on_a_sunday_cancels_on_monday',
                dict(entry, synthetic={'type': 'good_till_time', 'until_time': '14:30'}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=14, minute=31).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_time_stop_in_minutes_on_a_sunday_is_refused',
                dict(entry, synthetic={'type': 'time_stop', 'minutes': 20}),
                [],
                FROZEN_NOW.replace(day=27).replace(hour=11).timestamp(),
                accepted,
                taken_at=FROZEN_NOW.replace(day=27),
            ),
            self.clock_result(
                'a_time_stop_closes_what_it_filled',
                dict(entry, synthetic={
                    'type': 'time_stop',
                    'until_time': '10:30',
                }),
                [
                    self.update('26091500000021', 'OPEN', 6),
                ],
                frozen + 1900,
                accepted,
            ),
            self.clock_result(
                'a_time_stop_closes_an_entry_that_filled_completely',
                dict(entry, synthetic={
                    'type': 'time_stop',
                    'until_time': '10:30',
                }),
                [
                    self.update('26091500000021', 'COMPLETE', 10),
                ],
                frozen + 1900,
                accepted,
            ),
            self.clock_result(
                'a_time_stop_that_filled_nothing_just_cancels',
                dict(entry, synthetic={
                    'type': 'time_stop',
                    'until_time': '10:30',
                }),
                [],
                frozen + 1900,
                accepted,
            ),
            self.clock_result(
                'a_twap_sends_its_slices_on_the_clock',
                dict(entry, quantity=10, synthetic={
                    'type': 'twap',
                    'slices': 4,
                    'over_minutes': 20,
                }),
                [],
                frozen + 400,
                accepted,
            ),
            self.clock_result(
                'a_twap_sends_nothing_before_its_next_slice_is_due',
                dict(entry, quantity=10, synthetic={
                    'type': 'twap',
                    'slices': 4,
                    'over_minutes': 20,
                }),
                [],
                frozen + 10,
                accepted,
            ),
            self.clock_result(
                'a_daily_stop_places_a_fresh_stop_in_the_morning',
                dict(entry, synthetic={
                    'type': 'daily_stop',
                    'stop_price': 990,
                    'stop_limit_price': 988,
                    'arm_at': '09:20',
                }),
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                quote=self.scenarios.quote(),
                positions=10,
            ),
            self.clock_result(
                'a_daily_stop_closes_the_position_when_the_open_gapped_past_it',
                dict(entry, synthetic={
                    'type': 'daily_stop',
                    'stop_price': 990,
                    'stop_limit_price': 988,
                    'arm_at': '09:20',
                }),
                [],
                frozen + 60,
                accepted,
                taken_at=FROZEN_NOW.replace(hour=8, minute=45),
                quote=self.scenarios.quote(
                    last_price=960.00,
                    depth={
                        'buy': [
                            {'price': 960.00, 'quantity': 100, 'orders': 1},
                        ],
                        'sell': [
                            {'price': 960.05, 'quantity': 100, 'orders': 1},
                        ],
                    },
                ),
                positions=10,
            ),
            self.clock_result(
                'a_square_off_cancels_what_is_resting_and_closes_what_is_held',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
            ),
            self.clock_result(
                'a_square_off_records_the_cancel_of_an_order_placed_outside_the_engine',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
                resting=[
                    '26091500000077',
                ],
            ),
            self.clock_result(
                'a_square_off_closes_a_position_split_across_brokers_at_each_broker',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions={
                    'flattrade': 5,
                    'zerodha': 3,
                },
            ),
            self.clock_result(
                'a_square_off_cancels_a_resting_stop_before_closing',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
                resting=[
                    '26091500000078',
                ],
                resting_status='PENDING',
            ),
            self.clock_result(
                'a_square_off_closes_a_carry_position_with_a_carry_order',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                    'product': 'carry',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
                positions=8,
                position_product='NRML',
            ),
            self.clock_result(
                'a_square_off_with_nothing_held_closes_nothing',
                dict(entry, synthetic={
                    'type': 'square_off',
                    'at_time': '15:10',
                }),
                [],
                frozen + 20000,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.clock_result(
                'an_accumulation_buys_again_when_its_gap_is_up',
                dict(entry, quantity=5, synthetic={
                    'type': 'accumulation',
                    'every_minutes': 30,
                    'purchases': 4,
                }),
                [],
                frozen + 2000,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.priced_clock_result(
                'an_accumulation_never_bids_above_the_callers_limit',
                dict(entry, quantity=5, price=995, synthetic={
                    'type': 'accumulation',
                    'every_minutes': 30,
                    'purchases': 4,
                }),
                self.scenarios.quote(),
            ),
            self.priced_clock_result(
                'an_accumulation_rests_on_the_bid_when_it_is_better_than_the_limit',
                dict(entry, quantity=5, price=1005, synthetic={
                    'type': 'accumulation',
                    'every_minutes': 30,
                    'purchases': 4,
                }),
                self.scenarios.quote(),
            ),
            self.priced_clock_result(
                'an_accumulation_with_no_bid_rests_at_the_callers_limit',
                dict(entry, quantity=5, price=995, synthetic={
                    'type': 'accumulation',
                    'every_minutes': 30,
                    'purchases': 4,
                }),
                self.scenarios.quote(depth={
                    'buy': [],
                    'sell': [],
                }),
            ),
            self.clock_result(
                'an_accumulation_waits_out_the_gap_between_purchases',
                dict(entry, quantity=5, synthetic={
                    'type': 'accumulation',
                    'every_minutes': 30,
                    'purchases': 4,
                }),
                [],
                frozen + 60,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.clock_result(
                'a_vwap_gives_the_busiest_part_of_the_day_the_biggest_slice',
                dict(entry, quantity=100, synthetic={
                    'type': 'vwap',
                    'slices': 4,
                    'over_minutes': 240,
                }),
                [],
                frozen + 20000,
                accepted,
            ),
            self.clock_result(
                'a_vwap_can_be_given_a_profile_of_its_own',
                dict(entry, quantity=100, synthetic={
                    'type': 'vwap',
                    'slices': 4,
                    'over_minutes': 240,
                    'volume_profile': [1, 1, 1, 9, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                }),
                [],
                frozen + 20000,
                accepted,
            ),
            self.clock_result(
                'a_vwap_on_a_commodity_with_no_profile_of_its_own_sends_even_slices',
                dict(entry, quantity=400, instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['crudeoil_future'], synthetic={
                    'type': 'vwap',
                    'slices': 4,
                    'over_minutes': 240,
                }),
                [],
                frozen + 20000,
                accepted,
            ),
            self.clock_result(
                'an_implementation_shortfall_order_front_loads_its_slices',
                dict(entry, quantity=100, synthetic={
                    'type': 'implementation_shortfall',
                    'slices': 4,
                    'over_minutes': 20,
                    'urgency': 1,
                }),
                [],
                frozen + 2000,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.clock_result(
                'an_implementation_shortfall_order_at_zero_urgency_is_a_twap',
                dict(entry, quantity=100, synthetic={
                    'type': 'implementation_shortfall',
                    'slices': 4,
                    'over_minutes': 20,
                    'urgency': 0,
                }),
                [],
                frozen + 2000,
                accepted,
                quote=self.scenarios.quote(),
            ),
            self.clock_result(
                'a_time_that_has_already_passed_is_refused',
                dict(entry, synthetic={
                    'type': 'scheduled',
                    'at_time': '09:30',
                }),
                [],
                frozen + 60,
                accepted,
            ),
        ]

    def book_at(self, bid, offer):
        """A quote whose touch sits where a scenario wants it, with five levels behind each side.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quote.
        """
        return self.scenarios.quote(
            last_price=offer,
            depth={
                'buy': [
                    {
                        'price': round(bid - index * 0.05, 2),
                        'quantity': 100,
                        'orders': 1,
                    }
                    for index in range(5)
                ],
                'sell': [
                    {
                        'price': round(offer + index * 0.05, 2),
                        'quantity': 100,
                        'orders': 1,
                    }
                    for index in range(5)
                ],
            },
        )

    def run_price_checks(self):
        """Runs the types that watch the market, which is the only way they do anything.

        Returns:
            list: One recorded result per check.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        identifiers = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS
        steady = self.book_at(1000.00, 1000.05)
        return [
            self.price_result(
                'a_peg_follows_the_bid_it_is_pegged_to',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 1},
                    {'quote': self.book_at(999.80, 999.85), 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'every_move_of_a_peg_counts_against_the_daily_cap',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 1},
                    {'quote': self.book_at(999.80, 999.85), 'at': 2},
                ],
                accepted,
                daily_caps={
                    'flattrade': 100,
                },
                daily_sent={},
            ),
            self.price_result(
                'a_peg_stops_moving_its_entry_inside_the_exit_reserve',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 1},
                    {'quote': self.book_at(999.80, 999.85), 'at': 2},
                ],
                accepted,
                daily_caps={
                    'flattrade': 100,
                },
                daily_sent={
                    'flattrade': 94,
                },
            ),
            self.price_result(
                'a_peg_sends_nothing_while_the_bid_stands_still',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                    {'quote': steady, 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_peg_will_not_follow_the_bid_past_its_cap',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                    'cap_price': 1000.10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.50, 1000.55), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_peg_to_the_midpoint_rests_between_the_touch',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'mid',
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.10), 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.30), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_peg_held_back_by_the_throttle_does_not_move',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.20, 1000.25), 'at': 1},
                    {'quote': self.book_at(1000.40, 1000.45), 'at': 2},
                ],
                accepted,
                throttle_seconds=30,
            ),
            self.price_result(
                'a_peg_does_nothing_on_a_tick_that_carried_no_quote',
                dict(entry, synthetic={
                    'type': 'peg',
                    'reference': 'own_touch',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': None, 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_chaser_steps_towards_the_market_when_its_wait_is_up',
                dict(entry, synthetic={
                    'type': 'chaser',
                    'step_ticks': 1,
                    'step_seconds': 5,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                    {'quote': steady, 'at': 6},
                    {'quote': steady, 'at': 7},
                    {'quote': steady, 'at': 12},
                ],
                accepted,
            ),
            self.price_result(
                'a_chaser_will_not_step_past_its_cap',
                dict(entry, synthetic={
                    'type': 'chaser',
                    'step_ticks': 1,
                    'step_seconds': 5,
                    'cap_price': 1000.05,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 6},
                    {'quote': steady, 'at': 12},
                ],
                accepted,
            ),
            self.price_result(
                'a_strategy_stop_closes_every_leg_when_the_total_is_past_its_limit',
                dict(entry, synthetic={
                    'type': 'strategy_stop',
                    'loss_limit': -500,
                    'candidates': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'quantity': 10,
                            'price': 1000,
                        },
                        {
                            'instrument_id': identifiers['kwil'],
                            'transaction_type': 'SELL',
                            'quantity': 10,
                            'price': 250,
                        },
                    ],
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(900.00, 900.05), 'at': 1},
                ],
                accepted,
                fills=[
                    self.update('26091500000021', 'COMPLETE', 10,
                                average_price=1000.0),
                ],
            ),
            self.price_result(
                'a_strategy_stop_leaves_a_strategy_inside_its_limits_alone',
                dict(entry, synthetic={
                    'type': 'strategy_stop',
                    'loss_limit': -500,
                    'candidates': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'quantity': 10,
                            'price': 1000,
                        },
                        {
                            'instrument_id': identifiers['kwil'],
                            'transaction_type': 'SELL',
                            'quantity': 10,
                            'price': 250,
                        },
                    ],
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 1},
                ],
                accepted,
                fills=[
                    self.update('26091500000021', 'COMPLETE', 10,
                                average_price=1000.0),
                ],
            ),
            self.price_result(
                'an_exposure_hedge_trades_when_the_band_is_left',
                dict(entry, synthetic={
                    'type': 'exposure_hedge',
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance'],
                    'hedge_exposure_per_unit': 1,
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=100,
            ),
            self.price_result(
                'an_exposure_hedge_prices_a_hedge_in_another_instrument_from_that_instruments_quote',
                dict(entry, synthetic={
                    'type': 'exposure_hedge',
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance_future'],
                    'hedge_exposure_per_unit': 0.2,
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.book_at(1004.10, 1004.30),
                        },
                    },
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=100,
            ),
            self.price_result(
                'an_exposure_hedge_inside_its_band_does_nothing',
                dict(entry, synthetic={
                    'type': 'exposure_hedge',
                    'watched': [
                        {
                            'instrument_id': identifiers['reliance'],
                            'exposure_per_unit': 1,
                        },
                    ],
                    'hedge_instrument_id': identifiers['reliance'],
                    'lower_band': -10,
                    'upper_band': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=5,
            ),
            self.price_result(
                'a_participation_order_takes_a_share_of_what_the_market_trades',
                dict(entry, quantity=100, synthetic={
                    'type': 'participation',
                    'participation_percent': 10,
                }),
                [
                    {'quote': steady | {'volume': 10000}, 'at': 0},
                    {'quote': steady | {'volume': 10300}, 'at': 1},
                    {'quote': steady | {'volume': 10300}, 'at': 2},
                    {'quote': steady | {'volume': 10500}, 'at': 3},
                ],
                accepted,
            ),
            self.price_result(
                'a_participation_order_sends_nothing_for_a_share_below_one_unit',
                dict(entry, quantity=100, synthetic={
                    'type': 'participation',
                    'participation_percent': 1,
                }),
                [
                    {'quote': steady | {'volume': 10000}, 'at': 0},
                    {'quote': steady | {'volume': 10050}, 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_liquidity_seeking_order_strikes_when_the_size_appears',
                dict(entry, quantity=500, synthetic={
                    'type': 'liquidity_seeking',
                    'limit_price': 1000.10,
                    'minimum_quantity': 300,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': self.scenarios.quote(depth={
                            'buy': [{'price': 1000.00, 'quantity': 100, 'orders': 1}],
                            'sell': [
                                {'price': 1000.05, 'quantity': 200, 'orders': 2},
                                {'price': 1000.10, 'quantity': 250, 'orders': 3},
                                {'price': 1000.15, 'quantity': 900, 'orders': 4},
                            ],
                        }),
                        'at': 1,
                    },
                ],
                accepted,
            ),
            self.price_result(
                'a_liquidity_seeking_order_ignores_size_beyond_its_limit',
                dict(entry, quantity=500, synthetic={
                    'type': 'liquidity_seeking',
                    'limit_price': 1000.10,
                    'minimum_quantity': 300,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': self.scenarios.quote(depth={
                            'buy': [{'price': 1000.00, 'quantity': 100, 'orders': 1}],
                            'sell': [
                                {'price': 1000.05, 'quantity': 50, 'orders': 1},
                                {'price': 1000.15, 'quantity': 900, 'orders': 4},
                            ],
                        }),
                        'at': 1,
                    },
                ],
                accepted,
            ),
            self.price_result(
                'a_post_only_order_refuses_a_price_that_would_cross',
                dict(entry, price=1000.10, synthetic={
                    'type': 'post_only',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_post_only_order_can_be_told_to_rest_at_the_touch_instead',
                dict(entry, price=1000.10, synthetic={
                    'type': 'post_only',
                    'on_crossing': 'rest',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_post_only_order_that_rests_is_sent_untouched',
                dict(entry, price=999.50, synthetic={
                    'type': 'post_only',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_discretionary_order_takes_the_offer_when_it_comes_within_reach',
                dict(entry, price=1000.00, synthetic={
                    'type': 'discretionary',
                    'discretion_points': 0.25,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.20), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_discretionary_order_leaves_the_rest_showing_when_it_takes_a_slice',
                dict(entry, price=1000.00, synthetic={
                    'type': 'discretionary',
                    'discretion_points': 0.25,
                    'discretion_quantity': 4,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.20), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_discretionary_order_waits_while_the_offer_stays_out_of_reach',
                dict(entry, price=1000.00, synthetic={
                    'type': 'discretionary',
                    'discretion_points': 0.25,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.40), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_multi_day_trigger_fires_on_the_day_the_level_is_touched',
                dict(entry, synthetic={
                    'type': 'gtt',
                    'trigger_price': 995,
                    'limit_price': 990,
                    'valid_days': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_multi_day_trigger_expires_once_it_has_waited_long_enough',
                dict(entry, synthetic={
                    'type': 'gtt',
                    'trigger_price': 900,
                    'limit_price': 890,
                    'valid_days': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 60 * 60 * 25},
                ],
                accepted,
            ),
            self.price_result(
                'a_candle_close_stop_sits_through_a_wick',
                dict(entry, synthetic={
                    'type': 'candle_close_stop',
                    'trigger_price': 995,
                    'bar_minutes': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 10},
                    {'quote': steady, 'at': 50},
                    {'quote': steady, 'at': 70},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'a_candle_close_stop_fires_on_a_bar_that_closed_below',
                dict(entry, synthetic={
                    'type': 'candle_close_stop',
                    'trigger_price': 995,
                    'bar_minutes': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(990.00, 990.05), 'at': 10},
                    {'quote': self.book_at(990.00, 990.05), 'at': 50},
                    {'quote': self.book_at(990.00, 990.05), 'at': 70},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'an_average_range_trail_uses_its_fixed_fallback_until_it_has_bars',
                dict(entry, synthetic={
                    'type': 'atr_trail',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'bar_minutes': 1,
                    'periods': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 1},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'an_average_range_trail_widens_once_enough_bars_have_closed',
                dict(entry, synthetic={
                    'type': 'atr_trail',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'bar_minutes': 1,
                    'periods': 2,
                    'atr_multiple': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1040.00, 1040.05), 'at': 10},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 70},
                    {'quote': self.book_at(1060.00, 1060.05), 'at': 130},
                    {'quote': self.book_at(1080.00, 1080.05), 'at': 190},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_trailing_stop_follows_a_rising_market_and_not_a_falling_one',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 1},
                    {'quote': self.book_at(1040.00, 1040.05), 'at': 2},
                    {'quote': self.book_at(1015.00, 1015.05), 'at': 3},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_trailing_stop_measured_as_a_percentage_widens_as_it_goes',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_percent': 1,
                    'stop_limit_offset': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1100.00, 1100.05), 'at': 1},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_trailing_stop_ignores_a_move_smaller_than_its_step',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'step_ticks': 40,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.50, 1000.55), 'at': 1},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 2},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_trailing_entry_follows_a_falling_market_down',
                dict(entry, synthetic={
                    'type': 'trailing_entry',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(980.00, 980.05), 'at': 1},
                    {'quote': self.book_at(960.00, 960.05), 'at': 2},
                    {'quote': self.book_at(985.00, 985.05), 'at': 3},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
            ),
            self.price_result(
                'a_trailing_order_without_a_distance_is_refused',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'stop_limit_offset': 2,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.05,
                },
            ),
            self.price_result(
                'a_trailing_take_profit_waits_for_its_level_and_then_trails',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'activate_at': 1030,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 1},
                    {'quote': self.book_at(1035.00, 1035.05), 'at': 2},
                    {'quote': self.book_at(1050.00, 1050.05), 'at': 3},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 1025.05,
                },
                positions=10,
            ),
            self.price_result(
                'a_trailing_take_profit_places_nothing_below_its_level',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'activate_at': 1030,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1020.00, 1020.05), 'at': 1},
                    {'quote': self.book_at(990.00, 990.05), 'at': 2},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'a_trailing_take_profit_with_a_level_below_zero_is_refused',
                dict(entry, synthetic={
                    'type': 'trailing_stop',
                    'trail_points': 10,
                    'stop_limit_offset': 2,
                    'activate_at': -5,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_stepped_stop_moves_at_each_milestone_and_then_trails',
                dict(entry, synthetic={
                    'type': 'stepped_stop',
                    'entry_price': 1000,
                    'stop_price': 990,
                    'stop_limit_offset': 2,
                    'rules': [
                        {
                            'gain': 20,
                            'stop_at_gain': 0,
                        },
                        {
                            'gain': 40,
                            'stop_at_gain': 15,
                        },
                        {
                            'gain': 60,
                            'trail_points': 25,
                        },
                    ],
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1024.95, 1025.00), 'at': 1},
                    {'quote': self.book_at(1044.95, 1045.00), 'at': 2},
                    {'quote': self.book_at(1029.95, 1030.00), 'at': 3},
                    {'quote': self.book_at(1069.95, 1070.00), 'at': 4},
                    {'quote': self.book_at(1079.95, 1080.00), 'at': 5},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.0,
                },
                positions=10,
            ),
            self.price_result(
                'a_stepped_stop_that_jumps_past_every_milestone_starts_trailing',
                dict(entry, synthetic={
                    'type': 'stepped_stop',
                    'entry_price': 1000,
                    'stop_price': 990,
                    'stop_limit_offset': 2,
                    'rules': [
                        {
                            'gain': 20,
                            'stop_at_gain': 0,
                        },
                        {
                            'gain': 40,
                            'stop_at_gain': 15,
                        },
                        {
                            'gain': 60,
                            'trail_points': 25,
                        },
                    ],
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1064.95, 1065.00), 'at': 1},
                ],
                accepted,
                book_overrides={
                    'order_type': 'SL',
                    'trigger_price': 990.0,
                },
                positions=10,
            ),
            self.price_result(
                'a_stepped_stop_with_a_trail_before_its_last_rule_is_refused',
                dict(entry, synthetic={
                    'type': 'stepped_stop',
                    'entry_price': 1000,
                    'stop_price': 990,
                    'stop_limit_offset': 2,
                    'rules': [{'gain': 20, 'trail_points': 10}, {'gain': 40, 'stop_at_gain': 15}],
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_stepped_stop_rule_that_would_fire_at_once_is_refused',
                dict(entry, synthetic={
                    'type': 'stepped_stop',
                    'entry_price': 1000,
                    'stop_price': 990,
                    'stop_limit_offset': 2,
                    'rules': [{'gain': 20, 'stop_at_gain': 20}],
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_held_limit_changed_while_held_fires_at_its_new_price_and_quantity',
                dict(entry, synthetic={
                    'type': 'virtual_limit',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'held_change': {
                            'price': '1000.05',
                            'quantity': 20,
                        },
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'held_change': {
                            'price': '999',
                        },
                    },
                ],
                accepted,
            ),
            self.price_result(
                'a_market_if_touched_order_waits_and_then_takes_the_offer',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.90, 994.95), 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_trigger_on_the_bid_fires_before_the_last_trade_gets_there',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                    'trigger_on': 'bid',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 995.20), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_double_last_trigger_starts_again_when_a_tick_falls_back',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                    'trigger_on': 'double_last',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(995.50, 995.55), 'at': 2},
                    {'quote': self.book_at(994.90, 994.95), 'at': 3},
                    {'quote': self.book_at(994.90, 994.95), 'at': 4},
                ],
                accepted,
            ),
            self.price_result(
                'a_held_trigger_waits_until_the_level_has_held_long_enough',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                    'trigger_on': 'held',
                    'hold_seconds': 5,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.90, 994.95), 'at': 3},
                    {'quote': self.book_at(994.90, 994.95), 'at': 7},
                ],
                accepted,
            ),
            self.price_result(
                'a_held_trigger_without_a_hold_time_is_refused',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                    'trigger_on': 'held',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_type_that_chooses_its_own_price_refuses_trigger_on',
                dict(entry, synthetic={
                    'type': 'hidden_stop',
                    'trigger_price': 995,
                    'backstop_price': 990,
                    'backstop_limit_price': 988,
                    'trigger_on': 'last',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_close_on_trigger_cancels_resting_orders_then_closes_the_long',
                dict(entry, synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.00, 994.05), 'at': 2},
                ],
                accepted,
                positions=75,
                resting=[
                    '26091500000077',
                ],
            ),
            self.price_result(
                'a_close_on_trigger_closes_a_position_split_across_brokers_at_each_broker',
                dict(entry, synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions={
                    'flattrade': 50,
                    'zerodha': 25,
                },
            ),
            self.price_result(
                'a_close_on_trigger_with_nothing_held_completes_without_an_order',
                dict(entry, synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions=0,
            ),
            self.price_result(
                'a_close_on_trigger_buys_back_a_short_when_the_price_rises',
                dict(entry, transaction_type='SELL', synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 1005,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1005.00, 1005.05), 'at': 1},
                ],
                accepted,
                positions=-40,
            ),
            self.price_result(
                'a_close_on_trigger_leaves_orders_on_another_product_alone',
                dict(entry, synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions=75,
                resting=[
                    {'order_id': '26091500000077', 'product': 'CNC'},
                    {'order_id': '26091500000078', 'product': 'MIS'},
                ],
            ),
            self.price_result(
                'a_close_on_trigger_refuses_a_change_to_the_close_it_will_send',
                dict(entry, synthetic={
                    'type': 'close_on_trigger',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1, 'held_change': {'part': 'root', 'quantity': 5}},
                    {'quote': steady, 'at': 2, 'held_change': {'part': 'root', 'price': '990'}},
                    {'quote': self.book_at(994.90, 994.95), 'at': 3},
                ],
                accepted,
                positions=75,
            ),
            self.price_result(
                'a_stop_and_reverse_reverses_a_short_with_a_buy_whatever_the_body_says',
                dict(entry, synthetic={
                    'type': 'stop_and_reverse',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {
                        'quote': self.book_at(994.90, 994.95),
                        'at': 2,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 75),
                        ],
                    },
                ],
                accepted,
                positions=-75,
            ),
            self.price_result(
                'a_cross_instrument_order_reads_the_watched_price_at_its_own_tick',
                dict(entry, synthetic={
                    'type': 'cross_instrument',
                    'watch_instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['usdinr_future'],
                    'trigger_price': 83.5,
                    'trigger_direction': 'at_or_above',
                    'limit_price': 1000,
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'usdinr_future': self.book_at(83.4925, 83.4950)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'usdinr_future': self.book_at(83.4950, 83.4975)}},
                    {'quote': steady, 'at': 2, 'other_quotes': {'usdinr_future': self.book_at(83.4975, 83.5000)}},
                ],
                accepted,
            ),
            self.price_result(
                'a_limit_if_touched_price_off_the_tick_is_refused_when_placed',
                dict(entry, synthetic={
                    'type': 'limit_if_touched',
                    'trigger_price': 995,
                    'limit_price': 990.03,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_stop_and_reverse_closes_then_reverses_once_the_close_fills',
                dict(entry, synthetic={
                    'type': 'stop_and_reverse',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.00, 994.05), 'at': 2},
                    {
                        'quote': self.book_at(994.00, 994.05),
                        'at': 3,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 75),
                        ],
                    },
                ],
                accepted,
                positions=75,
            ),
            self.price_result(
                'a_doubled_stop_and_reverse_sends_one_order_for_twice_the_position',
                dict(entry, synthetic={
                    'type': 'stop_and_reverse',
                    'trigger_price': 995,
                    'method': 'double',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions=75,
            ),
            self.price_result(
                'a_doubled_stop_and_reverse_doubles_each_brokers_share_at_that_broker',
                dict(entry, synthetic={
                    'type': 'stop_and_reverse',
                    'trigger_price': 995,
                    'method': 'double',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
                positions={
                    'flattrade': 50,
                    'zerodha': 25,
                },
            ),
            self.price_result(
                'a_stop_and_reverse_with_an_unknown_method_is_refused',
                dict(entry, synthetic={
                    'type': 'stop_and_reverse',
                    'trigger_price': 995,
                    'method': 'sideways',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'an_attached_hedge_sells_the_future_in_whole_lots_as_the_entry_fills',
                dict(entry, quantity=1000, synthetic={
                    'type': 'attached_hedge',
                    'hedge_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['reliance_future'],
                    'ratio': 1,
                }),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.scenarios.quote(),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'OPEN', 600),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 1000),
                        ],
                    },
                ],
                accepted,
            ),
            self.price_result(
                'an_attached_hedge_sized_by_delta_sells_about_half_a_bought_call',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                    quantity=1500,
                    price=160,
                    synthetic={
                        'type': 'attached_hedge',
                        'hedge_instrument_id': order_routes.OrderRoutesState.
                        INSTRUMENT_IDENTIFIERS['reliance_future'],
                        'delta_volatility': 12.5,
                    },
                ),
                [
                    {
                        'quote': steady,
                        'at': 0,
                        'other_quotes': {
                            'reliance_future': self.scenarios.quote(last_price=25000),
                        },
                    },
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000021', 'COMPLETE', 1500),
                        ],
                    },
                ],
                accepted,
            ),
            self.price_result(
                'an_attached_hedge_with_both_a_ratio_and_a_delta_is_refused',
                dict(entry, synthetic={
                    'type': 'attached_hedge',
                    'hedge_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['reliance_future'],
                    'ratio': 1,
                    'delta_volatility': 12.5,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'an_attached_hedge_sized_by_delta_on_a_stock_is_refused',
                dict(entry, synthetic={
                    'type': 'attached_hedge',
                    'hedge_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['reliance_future'],
                    'delta_volatility': 12.5,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_scale_with_profit_taker_takes_each_rungs_profit_and_places_it_again',
                dict(entry, quantity=30, synthetic={
                    'type': 'scale_with_profit_taker',
                    'from_price': 1000,
                    'to_price': 990,
                    'steps': 3,
                    'profit_points': 4,
                    'most_cycles': 1,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000102', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 2,
                        'updates': [
                            self.update('26091500000104', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 3,
                        'updates': [
                            self.update('26091500000105', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 4,
                        'updates': [
                            self.update('26091500000106', 'COMPLETE', 10),
                        ],
                    },
                    {
                        'quote': steady,
                        'at': 5,
                        'updates': [
                            self.update('26091500000107', 'COMPLETE', 10),
                        ],
                    },
                ],
                dict(accepted, number_orders=True),
            ),
            self.price_result(
                'a_scale_with_profit_taker_without_a_profit_distance_is_refused',
                dict(entry, quantity=30, synthetic={
                    'type': 'scale_with_profit_taker',
                    'from_price': 1000,
                    'to_price': 990,
                    'steps': 3,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_two_sided_quote_follows_the_mid',
                dict(entry, synthetic={
                    'type': 'two_sided_quote',
                    'half_spread_points': 1,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1010.00, 1010.05), 'at': 1},
                ],
                dict(accepted, number_orders=True),
            ),
            self.price_result(
                'a_filled_bid_skews_the_ask_and_stops_buying_at_the_cap',
                dict(entry, synthetic={
                    'type': 'two_sided_quote',
                    'half_spread_points': 1,
                    'skew_ticks': 2,
                    'most_inventory': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': steady,
                        'at': 1,
                        'updates': [
                            self.update('26091500000101', 'COMPLETE', 10),
                        ],
                    },
                ],
                dict(accepted, number_orders=True),
            ),
            self.price_result(
                'a_two_sided_quote_without_a_spread_is_refused',
                dict(entry, synthetic={
                    'type': 'two_sided_quote',
                    'most_inventory': 10,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'an_account_conditional_order_waits_for_margin_to_free_up',
                dict(entry, synthetic={
                    'type': 'account_conditional',
                    'account_field': 'available_balance',
                    'account_level': 50000,
                    'trigger_direction': 'at_or_above',
                }),
                [
                    {'quote': steady, 'at': 0, 'funds': {'summary': {'available_balance': 40000.0}, 'pnl': {'realized': 0.0, 'unrealized': 0.0}}},
                    {'quote': steady, 'at': 1, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': 0.0, 'unrealized': 0.0}}},
                ],
                accepted,
            ),
            self.price_result(
                'an_account_conditional_order_is_cancelled_when_the_day_loss_is_reached',
                dict(entry, synthetic={
                    'type': 'account_conditional',
                    'account_field': 'day_pnl',
                    'account_level': -5000,
                    'trigger_direction': 'at_or_below',
                    'action': 'cancel',
                }),
                [
                    {'quote': steady, 'at': 0, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': -1000.0, 'unrealized': 0.0}}},
                    {'quote': steady, 'at': 1, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': -6000.0, 'unrealized': 0.0}}},
                ],
                accepted,
            ),
            self.price_result(
                'an_account_conditional_order_waits_while_a_position_is_open',
                dict(entry, synthetic={
                    'type': 'account_conditional',
                    'account_field': 'open_positions',
                    'account_level': 0,
                    'trigger_direction': 'at_or_below',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=75,
            ),
            self.price_result(
                'an_account_conditional_order_is_placed_once_the_book_is_flat',
                dict(entry, synthetic={
                    'type': 'account_conditional',
                    'account_field': 'open_positions',
                    'account_level': 0,
                    'trigger_direction': 'at_or_below',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=0,
            ),
            self.price_result(
                'an_account_conditional_order_without_a_direction_is_refused',
                dict(entry, synthetic={
                    'type': 'account_conditional',
                    'account_field': 'day_pnl',
                    'account_level': -5000,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_plan_account_conditional_order_waits_for_margin_to_free_up',
                dict(entry, synthetic={
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'account_conditional': {
                                    'account_field': 'available_balance',
                                    'account_level': 50000,
                                    'trigger_direction': 'at_or_above',
                                    },
                                },
                            ],
                        },
                    },
                }),
                [
                    {'quote': steady, 'at': 0, 'funds': {'summary': {'available_balance': 40000.0}, 'pnl': {'realized': 0.0, 'unrealized': 0.0}}},
                    {'quote': steady, 'at': 1, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': 0.0, 'unrealized': 0.0}}},
                ],
                accepted,
            ),
            self.price_result(
                'a_plan_account_conditional_order_is_cancelled_when_the_day_loss_is_reached',
                dict(entry, synthetic={
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'account_conditional': {
                                    'account_field': 'day_pnl',
                                    'account_level': -5000,
                                    'trigger_direction': 'at_or_below',
                                    'action': 'cancel',
                                    },
                                },
                            ],
                        },
                    },
                }),
                [
                    {'quote': steady, 'at': 0, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': -1000.0, 'unrealized': 0.0}}},
                    {'quote': steady, 'at': 1, 'funds': {'summary': {'available_balance': 60000.0}, 'pnl': {'realized': -6000.0, 'unrealized': 0.0}}},
                ],
                accepted,
            ),
            self.price_result(
                'a_plan_account_conditional_order_waits_while_a_position_is_open',
                dict(entry, synthetic={
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'account_conditional': {
                                    'account_field': 'open_positions',
                                    'account_level': 0,
                                    'trigger_direction': 'at_or_below',
                                    },
                                },
                            ],
                        },
                    },
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                positions=75,
            ),
            self.price_result(
                'a_plan_account_conditional_order_is_placed_once_the_book_is_flat',
                dict(entry, synthetic={
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'account_conditional': {
                                    'account_field': 'open_positions',
                                    'account_level': 0,
                                    'trigger_direction': 'at_or_below',
                                    },
                                },
                            ],
                        },
                    },
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
                positions=0,
            ),
            self.price_result(
                'a_plan_account_conditional_order_without_a_direction_is_refused',
                dict(entry, synthetic={
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'account_conditional': {
                                    'account_field': 'day_pnl',
                                    'account_level': -5000,
                                    },
                                },
                            ],
                        },
                    },
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_grid_with_one_rung_refused_answers_partial_with_207',
                dict(entry, synthetic={
                    'type': 'grid',
                    'levels': 1,
                    'step_points': 5,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                {
                    'sequence': [
                        accepted,
                        self.scenarios.answers.json_answer(200, self.scenarios.answers.place_refusal('flattrade')),
                    ],
                },
            ),
            self.price_result(
                'a_grid_with_every_rung_refused_answers_rejected',
                dict(entry, synthetic={
                    'type': 'grid',
                    'levels': 1,
                    'step_points': 5,
                    'most_inventory': 30,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                self.scenarios.answers.json_answer(200, self.scenarios.answers.place_refusal('flattrade')),
            ),
            self.price_result(
                'a_fired_trigger_does_not_fire_again_after_a_restart',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                    {'quote': self.book_at(994.90, 994.95), 'at': 2},
                ],
                accepted,
                restart_between_ticks=True,
            ),
            self.price_result(
                'a_virtual_limit_is_held_until_the_offer_reaches_its_price',
                dict(entry, price=999.50, synthetic={
                    'type': 'virtual_limit',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(999.50, 999.55), 'at': 1},
                    {
                        'quote': self.book_at(999.40, 999.45),
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 2,
                    },
                    {'quote': self.book_at(999.40, 999.45), 'at': 3},
                ],
                accepted,
            ),
            self.price_result(
                'a_virtual_limit_ignores_a_stale_quote',
                dict(entry, price=999.50, synthetic={
                    'type': 'virtual_limit',
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': dict(self.book_at(999.40, 999.45), stale=True),
                        'at': 1,
                    },
                    {'quote': self.book_at(999.40, 999.45), 'at': 2},
                ],
                accepted,
            ),
            self.price_result(
                'a_virtual_limit_must_be_a_limit_order',
                dict(entry, order_type='MARKET', price=None, synthetic={
                    'type': 'virtual_limit',
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_paper_virtual_limit_fills_from_the_queue_estimate',
                dict(entry, price=999.50, synthetic={
                    'type': 'virtual_limit',
                    'paper': True,
                }),
                [
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 0,
                            'filled': 0,
                        },
                        'at': 0,
                    },
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 1,
                    },
                    {
                        'quote': self.book_at(999.40, 999.45),
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 10,
                        },
                        'at': 2,
                    },
                ],
                accepted,
            ),
            self.price_result(
                'a_paper_fill_is_not_repeated_after_a_restart',
                dict(entry, price=999.50, synthetic={
                    'type': 'virtual_limit',
                    'paper': True,
                }),
                [
                    {
                        'quote': steady,
                        'estimate': {
                            'queue_filled': 4,
                            'filled': 4,
                        },
                        'at': 0,
                    },
                    {'quote': steady, 'at': 1},
                ],
                accepted,
                restart_between_ticks=True,
            ),
            self.price_result(
                'a_market_if_touched_order_that_is_never_touched_sends_nothing',
                dict(entry, synthetic={
                    'type': 'market_if_touched',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(1000.50, 1000.55), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_limit_if_touched_order_rests_at_the_price_it_was_given',
                dict(entry, synthetic={
                    'type': 'limit_if_touched',
                    'trigger_price': 995,
                    'limit_price': 990,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'a_hidden_stop_rests_a_backstop_and_fires_on_the_bid',
                dict(entry, synthetic={
                    'type': 'hidden_stop',
                    'trigger_price': 995,
                    'backstop_price': 990,
                    'backstop_limit_price': 988,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 995.20), 'at': 1},
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'a_hidden_stop_is_not_fired_by_a_last_trade_the_book_never_reached',
                dict(entry, synthetic={
                    'type': 'hidden_stop',
                    'trigger_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': self.book_at(1000.00, 1000.05) | {
                            'last_price': 990.00,
                        },
                        'at': 1,
                    },
                ],
                accepted,
                positions=10,
            ),
            self.price_result(
                'a_cross_instrument_order_is_fired_by_the_instrument_it_watches',
                dict(entry, synthetic={
                    'type': 'cross_instrument',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['reliance'],
                    'trigger_price': 995,
                    'limit_price': 990,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {'quote': self.book_at(994.90, 994.95), 'at': 1},
                ],
                accepted,
            ),
            self.price_result(
                'an_underlying_peg_moves_with_the_index_by_its_delta',
                dict(entry, synthetic={
                    'type': 'underlying_peg',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['nifty_index'],
                    'delta': 0.5,
                    'step_ticks': 20,
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25040)}},
                    {'quote': steady, 'at': 2, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25041)}},
                    {'quote': steady, 'at': 3, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=24960)}},
                ],
                accepted,
            ),
            self.price_result(
                'an_underlying_peg_stays_inside_its_range',
                dict(entry, synthetic={
                    'type': 'underlying_peg',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['nifty_index'],
                    'delta': 0.5,
                    'highest_price': 1010,
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25100)}},
                ],
                accepted,
            ),
            self.price_result(
                'an_underlying_peg_without_a_delta_is_refused',
                dict(entry, synthetic={
                    'type': 'underlying_peg',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['nifty_index'],
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                ],
                accepted,
            ),
            self.price_result(
                'an_underlying_peg_on_its_own_instrument_is_refused',
                dict(entry, synthetic={
                    'type': 'underlying_peg',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['reliance'],
                    'delta': 0.5,
                }),
                [
                    {'quote': steady, 'at': 0},
                ],
                accepted,
            ),
            self.price_result(
                'a_volatility_order_is_priced_by_the_model_and_follows_the_index',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                    quantity=75,
                    price=500,
                    synthetic={
                        'type': 'volatility',
                        'watch_instrument_id': order_routes.OrderRoutesState.
                        INSTRUMENT_IDENTIFIERS['nifty_index'],
                        'volatility': 12.5,
                    },
                ),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 2, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25100)}},
                ],
                accepted,
            ),
            self.price_result(
                'a_volatility_order_never_pays_more_than_its_own_price',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                    quantity=75,
                    price=150,
                    synthetic={
                        'type': 'volatility',
                        'watch_instrument_id': order_routes.OrderRoutesState.
                        INSTRUMENT_IDENTIFIERS['nifty_index'],
                        'volatility': 12.5,
                    },
                ),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                    {'quote': steady, 'at': 1, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=24900)}},
                ],
                accepted,
            ),
            self.price_result(
                'a_volatility_order_without_a_volatility_is_refused',
                dict(
                    entry,
                    instrument_id=order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['nifty_option'],
                    quantity=75,
                    price=500,
                    synthetic={
                        'type': 'volatility',
                        'watch_instrument_id': order_routes.OrderRoutesState.
                        INSTRUMENT_IDENTIFIERS['nifty_index'],
                    },
                ),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                ],
                accepted,
            ),
            self.price_result(
                'a_volatility_order_on_something_that_is_not_an_option_is_refused',
                dict(entry, synthetic={
                    'type': 'volatility',
                    'watch_instrument_id': order_routes.OrderRoutesState.
                    INSTRUMENT_IDENTIFIERS['nifty_index'],
                    'volatility': 12.5,
                }),
                [
                    {'quote': steady, 'at': 0, 'other_quotes': {'nifty_index': self.scenarios.quote(last_price=25000)}},
                ],
                accepted,
            ),
            self.price_result(
                'an_indicator_triggered_order_watches_the_day_average',
                dict(entry, synthetic={
                    'type': 'indicator_triggered',
                    'watch_field': 'average_price',
                    'trigger_price': 999,
                    'limit_price': 995,
                }),
                [
                    {'quote': steady, 'at': 0},
                    {
                        'quote': self.book_at(1000.00, 1000.05) | {
                            'average_price': 998.50,
                        },
                        'at': 1,
                    },
                ],
                accepted,
            ),
            self.price_result(
                'a_chaser_crosses_the_spread_once_its_time_is_up',
                dict(entry, synthetic={
                    'type': 'chaser',
                    'step_ticks': 1,
                    'step_seconds': 5,
                    'cross_after_seconds': 10,
                }),
                [
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 0},
                    {'quote': self.book_at(1000.00, 1000.50), 'at': 11},
                ],
                accepted,
            ),
        ]

    def run_daily_cap_race_checks(self):
        """Checks that threads sending at once to a broker near its daily cap cannot overshoot it, and that a place not used is given back.

        The count used to be read before a send and added to after it, so every thread sending in between passed on the same count.

        Returns:
            list: One recorded result per check.
        """
        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        daily_count = DailyOrderCount(
            self.fake_redis,
            {
                'flattrade': 10,
            },
            0.0,
            logger,
        )
        outcomes = []
        outcomes_lock = threading.Lock()
        start = threading.Barrier(20)
        threads = []
        for _ in range(20):
            thread = threading.Thread(
                target=self.race_for_a_place,
                args=(
                    daily_count,
                    start,
                    outcomes,
                    outcomes_lock,
                ),
            )
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        counted = outcomes.count('sent')
        results = [
            {
                'name': 'twenty_threads_racing_for_ten_places_send_exactly_ten',
                'sent': counted,
                'refused': outcomes.count('refused'),
                'count_in_redis': self.fake_redis.strings.get(daily_count.key('flattrade')),
            },
        ]
        self.fake_redis = self.build_state()
        daily_count = DailyOrderCount(
            self.fake_redis,
            {
                'flattrade': 10,
            },
            0.0,
            logger,
        )
        daily_count.refuse_if_capped('flattrade', False)
        after_reserving = self.fake_redis.strings.get(daily_count.key('flattrade'))
        daily_count.release_if_reserved()
        results.append({
            'name': 'a_place_counted_for_a_message_not_sent_is_given_back',
            'after_reserving': after_reserving,
            'after_releasing': self.fake_redis.strings.get(daily_count.key('flattrade')),
        })
        return results

    def race_for_a_place(self, daily_count, start, outcomes, outcomes_lock):
        """One thread's attempt to send a message to a capped broker: reserve a place, then count the send.

        Args:
            daily_count (DailyOrderCount): The count.
            start (threading.Barrier): Holds every thread until all are ready, so they race.
            outcomes (list): Where each thread writes `sent` or `refused`.
            outcomes_lock (threading.Lock): Guards `outcomes`.

        Returns:
            None: This method returns nothing.
        """
        start.wait()
        try:
            daily_count.refuse_if_capped('flattrade', False)
        except RefusedRequestError:
            with outcomes_lock:
                outcomes.append('refused')
            return
        daily_count.count_sent('flattrade')
        with outcomes_lock:
            outcomes.append('sent')

    def run_quantity_conversion_checks(self):
        """Checks that a leg reduced in units is sent in each broker's own terms.

        `reduce_leg` sent units to `modify_leg`, which sends them unchanged, so a crude oil exit reduced to 300 units reached a broker that counts lots as 300 lots.

        Returns:
            list: One recorded result per check.
        """
        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        crude = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['crudeoil_future']
        results = []
        conversions = {}
        for broker_name in ('dhan', 'flattrade', 'kotak', 'zerodha'):
            conversions[broker_name] = placement.broker_quantity(broker_name, crude, 300)
        results.append({
            'name': 'three_hundred_units_of_crude_in_each_brokers_terms',
            'converted': conversions,
        })
        try:
            placement.broker_quantity('zerodha', crude, 150)
            refusal = None
        except RefusedRequestError as error:
            refusal = error.body.get('error')
        results.append({
            'name': 'a_quantity_that_is_not_whole_lots_is_refused',
            'refusal': refusal,
        })
        recorder = ModifyRecorder()
        placement.modify_leg = recorder.modify_leg
        parent = ParentOrder('crude-parent')
        parent.synthetic_type = 'plan'
        parent.instrument_id = crude
        parent.body = {}
        leg = OrderLeg('crude-parent:1', 'root.each_fill.children.0')
        leg.broker = 'zerodha'
        leg.broker_order_id = '2104110000000001'
        leg.quantity = 300
        parent.legs.append(leg)
        runner = SYNTHETIC_ORDER_CLASSES['plan'](
            parent,
            placement,
            engine_stand_ins.RecordingEventLog(),
            ParentStore(self.fake_redis),
            logger,
            None,
        )
        accepted = runner.reduce_leg(leg, 200, 'the target filled 100')
        results.append({
            'name': 'a_crude_exit_reduced_to_200_units_is_sent_as_2_lots_to_zerodha',
            'accepted': accepted,
            'sent': recorder.sent,
        })
        return results

    def run_rotation_checks(self):
        """Checks that the round robin spreads a run of orders some brokers cannot take evenly over the brokers that can.

        In the live test of 2026-09-27, a burst of after-market orders gave INDmoney 30 of 100, because the broker after one that cannot take the order took two turns.

        Returns:
            list: One recorded result per check.
        """
        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        instrument_id = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']
        order = PlaceOrderRequest(self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            after_market=True,
        ))
        counts = {}
        refused = 0
        for _ in range(28):
            try:
                prepared = placement.prepare(order, instrument_id)
            except RefusedRequestError:
                refused = refused + 1
                continue
            counts[prepared.broker_name] = counts.get(prepared.broker_name, 0) + 1
        return [
            {
                'name': 'after_market_orders_are_spread_evenly_over_the_brokers_that_take_them',
                'orders': 28,
                'refused': refused,
                'per_broker': dict(sorted(counts.items())),
            },
        ]

    def run_stoxkart_algo_checks(self):
        """Checks that Stoxkart's placement carries the Algo-ID from its settings, and `99999` when they have none.

        Stoxkart refused every order with `invalid algo_id` on 2026-09-27 although it had accepted `99999` on 2026-09-15, so the id is now read from the broker's settings.

        Returns:
            list: One recorded result per check.
        """
        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        instrument_id = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']
        instrument, _, _ = placement.market_context(instrument_id, False, False)
        order = PlaceOrderRequest(self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
        ))
        stoxkart = StoxkartOrders()
        base_settings = {
            'ucc_code': 'SX000001',
            'api_key': 'stoxkart-api-key',
        }
        results = []
        for name, settings in (
            ('stoxkart_sends_99999_when_its_settings_name_no_algo_id', base_settings),
            ('stoxkart_sends_the_algo_id_its_settings_name', dict(base_settings, algo_id='123456')),
            ('stoxkart_treats_a_blank_algo_id_as_none', dict(base_settings, algo_id=' ')),
        ):
            request = stoxkart.build_place_request(
                order,
                instrument,
                instrument.handles.get('stoxkart') or {},
                {
                    'access_token': 'token',
                },
                settings,
            )
            results.append({
                'name': name,
                'header': request.headers.get('X-Algo-Id'),
                'body': request.json_body.get('algo_id'),
            })
        return results

    def run_rate_limit_checks(self):
        """Checks the per-broker rate limit setting and that a broker with its own limit is held to it.

        On 2026-09-27 Zerodha and INDmoney refused orders sent at 10 a second, so each broker can now be given its own limit.

        Returns:
            list: One recorded result per check.
        """
        logger = logging.getLogger('test_runs.order_engine')
        broker_names = [
            'dhan',
            'indmoney',
            'zerodha',
        ]
        results = []
        for text in (
            '10',
            10,
            '10,zerodha=5,indmoney=5',
            '10, zerodha = 4',
            '10,kite=5',
            '10,zerodha=fast',
            '10,zerodha=-1',
        ):
            try:
                default_limit, overrides = RateBudget.limits_from_text(text, broker_names)
                results.append({
                    'name': f'the_rate_setting_{text!r}_is_read',
                    'default': default_limit,
                    'overrides': overrides,
                })
            except ValueError as error:
                results.append({
                    'name': f'the_rate_setting_{text!r}_is_refused',
                    'error': str(error),
                })
        self.fake_redis = self.build_state()
        budget = RateBudget(self.fake_redis, 0, 10, 0, logger, 1.0, {
            'zerodha': 5,
        })
        taken = {}
        for broker_name in ('zerodha', 'dhan'):
            count = 0
            for _ in range(12):
                if budget.try_take(broker_name) == 0:
                    count = count + 1
            taken[broker_name] = count
        results.append({
            'name': 'a_broker_with_its_own_limit_is_held_to_it_within_one_window',
            'taken_of_12': taken,
        })
        return results

    def run_assignment_checks(self):
        """Checks that a leg the broker intake chose cannot take goes to one that can.

        Intake chooses a broker from the caller's body, which for an OCO or a trailing stop is a plain limit, while the type's first real leg is a stop-limit. On 2026-09-27 such legs were sent to INDmoney, which takes no stop-limit orders, and refused.

        Returns:
            list: One recorded result per check.
        """
        self.fake_redis = self.build_state()
        logger = logging.getLogger('test_runs.order_engine')
        placement = EnginePlacement(self.fake_redis, logger)
        instrument_id = order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']
        stop = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='SL',
            price=990,
            trigger_price=991,
            transaction_type='SELL',
        )
        limit = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
        )
        results = []
        for name, assigned, body in (
            ('a_stop_leg_assigned_to_a_broker_without_stops_goes_elsewhere', 'indmoney', stop),
            ('a_stop_leg_assigned_to_a_broker_with_stops_stays', 'flattrade', stop),
            ('a_limit_leg_assigned_to_a_broker_without_stops_stays', 'indmoney', limit),
        ):
            placement.use_assignment(assigned, [])
            try:
                prepared = placement.prepare(
                    PlaceOrderRequest(body),
                    instrument_id,
                )
                placed_at = prepared.broker_name
                error = None
            except RefusedRequestError as refusal:
                placed_at = None
                error = refusal.body.get('error')
            finally:
                placement.clear_assignment()
            results.append({
                'name': name,
                'assigned': assigned,
                'order_type': body['order_type'],
                'placed_at': placed_at,
                'error': error,
            })
        return results

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

    def run_carry_window_checks(self):
        """Checks that the rebuild after 06:00 still finds an order valid for longer than a month.

        A GTT may be valid for up to 365 days, and the rebuild reads carried orders' events that far back. The events here are a 60-day GTT placed on 20 August 2026, rebuilt 31 and 45 days later, when it is still valid.

        Returns:
            list: One recorded result per check, with the parents the rebuild found.
        """
        placed = datetime.datetime(2026, 8, 20, 10, 0, tzinfo=moments.INDIA)
        parameters = {
            'type': 'plan',
            'routed_from': 'gtt',
            'plan': {
                'order': {
                    'presets': [
                        {
                            'good_till_triggered': {
                                'trigger_price': 995,
                                'limit_price': 990,
                                'valid_days': 60,
                            },
                        },
                    ],
                },
            },
        }
        rows = [
            {
                'time': placed.isoformat(),
                'parent_order_id': 'gtt-sixty-days',
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'plan',
                'parent_state': 'received',
                'instrument_id': order_routes.OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance'],
                'detail': {
                    'parameters': parameters,
                },
            },
            {
                'time': (placed + datetime.timedelta(seconds=1)).isoformat(),
                'parent_order_id': 'gtt-sixty-days',
                'sequence': 2,
                'event': 'parameters_changed',
                'synthetic_type': 'plan',
                'parent_state': 'received',
                'detail': {
                    'parameters': dict(parameters, carries_overnight=True),
                },
            },
        ]
        results = []
        for days_later in [
            31,
            45,
        ]:
            now = datetime.datetime(2026, 8, 20, 7, 0, tzinfo=moments.INDIA) + datetime.timedelta(days=days_later)
            parent_store = ParentStore(redis_stand_ins.FakeEngineStoreRedis())
            parent_store.reset_epochs = lambda when=None, moment=now: ParentStore.reset_epochs(moment)
            recovery = EngineRecovery(
                parent_store.cache,
                engine_stand_ins.WindowedEventLog(rows),
                parent_store,
                order_routes.BROKER_NAMES,
                logging.getLogger('test_runs.order_engine'),
            )
            parents = recovery.replay()
            states = []
            for parent in parents:
                states.append(parent.state)
            results.append({
                'name': f'a_sixty_day_gtt_is_rebuilt_{days_later}_days_after_it_was_placed',
                'rebuilt': states,
            })
        return results

    def run_overnight_carry_checks(self):
        """Checks which timed orders are marked to outlive the 06:00 rebuild: those whose time falls on a later trading day, and not those due later the same day.

        At 06:00 IST the engine rebuilds its open orders from that day's record, and brings back an older parent only when it was marked `carries_overnight`. An order taken on a Sunday for Monday has no record on Monday until its time comes, so without the mark it would be dropped before it fired.

        Returns:
            list: One recorded result per check, with the stored parent's `carries_overnight`.
        """
        accepted = self.scenarios.answers.json_answer(
            200,
            self.scenarios.answers.place_success('flattrade'),
        )
        entry = self.scenarios.bodies.market_order(
            dry_run=None,
            order_type='LIMIT',
            price=1000,
            quantity=10,
        )
        sunday = FROZEN_NOW.replace(day=27)
        holiday = FROZEN_NOW.replace(month=10, day=2)
        cases = [
            ('a_scheduled_order_taken_on_a_sunday_carries_overnight', {'type': 'scheduled', 'at_time': '15:00'}, sunday),
            ('a_scheduled_order_taken_on_a_holiday_carries_overnight', {'type': 'scheduled', 'at_time': '15:00'}, holiday),
            ('a_scheduled_order_for_later_today_does_not_carry_overnight', {'type': 'scheduled', 'at_time': '15:00'}, FROZEN_NOW),
            ('a_good_till_time_order_taken_on_a_sunday_carries_overnight', {'type': 'good_till_time', 'until_time': '14:30'}, sunday),
            ('a_square_off_taken_on_a_sunday_carries_overnight', {'type': 'square_off', 'at_time': '15:10'}, sunday),
        ]
        results = []
        for name, synthetic, taken_at in cases:
            result = self.clock_result(
                name,
                dict(entry, synthetic=synthetic),
                [],
                taken_at.timestamp() + 60,
                accepted,
                taken_at=taken_at,
            )
            carries = []
            for document in self.fake_redis.hashes.get('unified:orders:parents', {}).values():
                parameters = json.loads(document).get('parameters') or {}
                carries.append(parameters.get('carries_overnight') is True)
            result['carries_overnight'] = carries
            results.append(result)
        return results

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
            'recovery_leaves_a_live_leg_as_recorded_for_the_first_book_pass',
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
            'the_first_book_pass_records_a_fill_made_while_the_engine_was_down',
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
            first_pass=True,
        ))
        results.append(self.recovery_result(
            'the_first_book_pass_ends_a_cancelling_parent_whose_order_was_cancelled_while_the_engine_was_down',
            crashed[:1] + [
                dict(
                    crashed[1],
                    leg_state='acknowledged',
                    broker_order_id='26091500000021',
                ),
                {
                    'time': '2026-09-23T10:00:03+00:00',
                    'parent_order_id': crashed[0]['parent_order_id'],
                    'sequence': 3,
                    'event': 'parent_state_changed',
                    'synthetic_type': 'simple',
                    'parent_state': 'cancelling',
                },
            ],
            {
                '26091500000021': self.book_order(
                    status='CANCELLED',
                ),
            },
            first_pass=True,
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
        original_now = moments.Moments.now
        requests.Session.request = self.network.request
        uuid.uuid4 = self.counting_uuid
        moments.Moments.now = lambda self: FROZEN_NOW
        api_configuration['order_excluded_brokers'] = [
            '',
        ]
        api_configuration['order_broker_selector'] = 'round_robin'
        original_hold_limits = api_configuration['order_hold_limits']
        api_configuration['order_hold_limits'] = False
        try:
            results = []
            for scenario in OrderEngineScenarios().build():
                results.append(self.run_scenario(scenario))
            results.append(self.run_lane_equivalence_check())
            results.extend(self.run_lock_checks())
            results.extend(self.run_parent_checks())
            results.extend(self.run_recovery_checks())
            results.extend(self.run_overnight_carry_checks())
            results.extend(self.run_carry_window_checks())
            results.extend(self.run_follower_checks())
            results.extend(self.run_reaction_checks())
            results.extend(self.run_plan_checks())
            results.extend(self.run_plan_trigger_checks())
            results.extend(self.run_plan_virtual_limit_checks())
            results.extend(self.run_plan_held_ladder_checks())
            results.extend(self.run_plan_hold_limits_checks())
            results.extend(self.run_holding_types_checks())
            results.extend(self.run_holding_joins_checks())
            results.extend(self.run_plan_kept_whole_checks())
            results.extend(self.run_plan_routing_checks())
            results.extend(self.run_plan_join_checks())
            results.extend(self.run_plan_trailing_checks())
            results.extend(self.run_plan_execution_checks())
            results.extend(self.run_plan_market_execution_checks())
            results.extend(self.run_plan_moving_price_checks())
            results.extend(self.run_plan_followed_price_checks())
            results.extend(self.run_plan_stage_stop_checks())
            results.extend(self.run_plan_lifetime_checks())
            results.extend(self.run_plan_group_checks())
            results.extend(self.run_plan_close_checks())
            results.extend(self.run_plan_repeat_checks())
            results.extend(self.run_plan_fill_follower_checks())
            results.extend(self.run_plan_change_checks())
            results.extend(self.run_plan_cancel_checks())
            results.extend(self.run_clock_checks())
            results.extend(self.run_closed_position_checks())
            results.extend(self.run_late_auction_and_whole_lot_checks())
            results.extend(self.run_breakout_exit_checks())
            results.extend(self.run_linked_order_checks())
            results.extend(self.run_stop_type_checks())
            results.extend(self.run_stale_quote_checks())
            results.extend(self.run_price_checks())
            results.extend(self.run_wiring_checks())
            results.extend(self.run_assignment_checks())
            results.extend(self.run_rate_limit_checks())
            results.extend(self.run_stoxkart_algo_checks())
            results.extend(self.run_rotation_checks())
            results.extend(self.run_quantity_conversion_checks())
            results.extend(self.run_daily_cap_race_checks())
        finally:
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            moments.Moments.now = original_now
            api_configuration['order_excluded_brokers'] = original_excluded
            api_configuration['order_broker_selector'] = original_selector
            api_configuration['order_hold_limits'] = original_hold_limits
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
