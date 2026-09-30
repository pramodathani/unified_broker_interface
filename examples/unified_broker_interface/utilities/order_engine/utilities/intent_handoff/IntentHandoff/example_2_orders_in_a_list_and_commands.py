"""Hands a list of orders, and then changes to orders the engine owns, to the engine in one round trip each.

The `orders` list form of `POST /api/orders/place` calls `place_many`. Every order becomes its own intent, but all of them name one shared reply list and their own place in the request, so the engine's workers can answer in any order and `collect_replies` still knows which answer is which. An order the engine has not answered when the wait ends is answered as outcome `unknown` with HTTP 504, because the engine may still place it.

The modify and cancel routes do the same for an order the engine placed, through `command` for one change and `command_many` for several. A command carries its arguments instead of an order body and names no instrument.

`PretendEngineRedis` stands in for Redis. Its `blpop` plays the engine, answering each intent written since it last looked, except an order whose tag is `slow01`, which it leaves unanswered so the program can show the unknown answer without waiting. The handoff is built with `hold_limits` on, so the plain day limit order is written as a `virtual_limit` for the engine's virtual order book while the IOC limit and the market order stay `simple`.

The last part calls `collect_replies` on a reply list filled by hand, to show that an answer it cannot read is skipped rather than stopping the collection.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/intent_handoff/IntentHandoff/example_2_orders_in_a_list_and_commands.py
"""

import json
import time

from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    ANSWER_KEY_PREFIX,
    INTENT_STREAM_KEY,
    IntentHandoff,
)

INFOSYS_ID = '11111111-1111-5111-8111-000000000001'
RELIANCE_ID = '11111111-1111-5111-8111-000000000004'
PARENT_ID = '5b1f2c9e-3d4a-4e8b-9c1d-2a7f6e0b4c31'


class PretendEngineRedis:
    """A stand-in for the Redis client whose reply lists are filled by a pretend order engine.

    A real API worker writes an intent to the stream and then blocks in `BLPOP` while the engine, in another process, places the order and pushes the answer. Here the answering happens inside `blpop`: before it looks at a reply list, the stand-in answers every intent written since it last looked, the way the engine's `reply` does, unless the intent's tag is one it has been told to leave unanswered.

    Attributes:
        engine_running (bool): Whether the engine's lock key exists.
        silent_tags (tuple): Tags of the orders the pretend engine never answers.
        stream (list): The intent documents written to the stream, oldest first.
        answered_count (int): How many stream entries the pretend engine has read.
        lists (dict): Reply list keys to the answers pushed onto them.
        strings (dict): Keys to the answers stored for a caller who stopped waiting.
    """

    def __init__(self, engine_running=True, silent_tags=()):
        """Builds the stand-in with an empty stream.

        Args:
            engine_running (bool): Whether the engine's lock key exists.
            silent_tags (tuple): Tags of the orders the pretend engine never answers.

        Returns:
            None: This method returns nothing.
        """
        self.engine_running = engine_running
        self.silent_tags = silent_tags
        self.stream = []
        self.answered_count = 0
        self.lists = {}
        self.strings = {}

    def exists(self, key):
        """Whether a key exists; only the engine's lock is ever asked about.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key is the engine's lock and the engine is running, otherwise 0.
        """
        if key == LOCK_KEY and self.engine_running:
            return 1
        return 0

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Appends one intent to the stream.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields, whose `intent` is the intent as JSON.
            maxlen (int | None): Accepted and ignored.
            approximate (bool): Accepted and ignored.

        Returns:
            str: The entry's id.
        """
        del key, maxlen, approximate
        self.stream.append(json.loads(fields['intent']))
        return f'{len(self.stream)}-0'

    def pipeline(self, transaction=True):
        """Starts a pipeline that sends its writes when executed.

        Args:
            transaction (bool): Accepted and ignored.

        Returns:
            PretendPipeline: The pipeline.
        """
        del transaction
        return PretendPipeline(self)

    def get(self, key):
        """Reads one stored answer.

        Args:
            key (str): The key.

        Returns:
            str | None: The stored text, or None.
        """
        return self.strings.get(key)

    def blpop(self, key, timeout=None):
        """Lets the pretend engine answer, then takes the first answer off a reply list without waiting.

        Args:
            key (str): The reply list.
            timeout (float | None): Accepted and ignored, since the stand-in never waits.

        Returns:
            tuple | None: `(key, answer_text)`, or None when nothing is on the list, as when a real wait runs out.
        """
        del timeout
        self.answer_waiting_intents()
        entries = self.lists.get(key)
        if not entries:
            return None
        return key, entries.pop(0)

    def answer_waiting_intents(self):
        """Answers every intent written since the last look, as the engine would.

        Returns:
            None: This method returns nothing.
        """
        while self.answered_count < len(self.stream):
            intent = self.stream[self.answered_count]
            self.answered_count = self.answered_count + 1
            if intent['body'].get('tag') in self.silent_tags:
                continue
            body = self.answer_body(intent)
            pushed = {
                'body': body,
                'status': 200,
            }
            if intent.get('request_index') is not None:
                pushed['request_index'] = intent['request_index']
                pushed['intent_id'] = intent['intent_id']
            self.lists.setdefault(intent['reply_key'], []).append(json.dumps(pushed))
            self.strings[ANSWER_KEY_PREFIX + intent['intent_id']] = json.dumps({
                'body': body,
                'status': 200,
            })

    def answer_body(self, intent):
        """The body the pretend engine answers an intent with.

        Args:
            intent (dict): The intent document.

        Returns:
            dict: A placement's answer for an order, or a leg change's answer for a command.
        """
        if intent.get('command'):
            return {
                'broker': intent['body']['broker'],
                'order_id': intent['body']['order_id'],
                'outcome': 'accepted',
                'status_message': None,
                'broker_response': {
                    'status': 'success',
                },
                'parent_id': intent['body']['parent_id'],
                'synthetic_type': 'simple',
            }
        order_id = f'2509300000{self.answered_count:05d}'
        return {
            'broker': 'zerodha',
            'instrument_id': intent['instrument_id'],
            'tag': intent['body'].get('tag'),
            'outcome': 'accepted',
            'order_id': order_id,
            'status_message': None,
            'broker_response': {
                'status': 'success',
                'data': {
                    'order_id': order_id,
                },
            },
            'skipped': [],
            'timing_ms': {
                'preparation': 0.25,
                'broker': 41.7,
            },
        }


class PretendPipeline:
    """A stand-in for a Redis pipeline that queues stream writes and sends them on `execute`.

    Attributes:
        cache (PretendEngineRedis): The stand-in the writes go to.
        queued (list): The queued entries' fields.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (PretendEngineRedis): The stand-in the writes go to.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.queued = []

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Queues one intent.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.
            maxlen (int | None): Accepted and ignored.
            approximate (bool): Accepted and ignored.

        Returns:
            None: This method returns nothing.
        """
        del key, maxlen, approximate
        self.queued.append(fields)

    def execute(self):
        """Sends every queued intent.

        Returns:
            list: One entry id per intent.
        """
        entry_ids = []
        for fields in self.queued:
            entry_ids.append(self.cache.xadd(INTENT_STREAM_KEY, fields))
        return entry_ids


class OrdersInAListAndCommandsExample:
    """Places three orders in one request, then cancels and changes legs the engine owns.

    Attributes:
        cache (PretendEngineRedis): The stand-in Redis client with its pretend engine.
        handoff (IntentHandoff): The handoff being shown, holding plain limit orders.
    """

    def __init__(self):
        """Builds the handoff over the stand-in, with limit orders held.

        Returns:
            None: This method returns nothing.
        """
        self.cache = PretendEngineRedis(silent_tags=(
            'slow01',
        ))
        self.handoff = IntentHandoff(self.cache, 10.0, hold_limits=True)

    def limit_order(self, validity, tag):
        """Builds one Infosys limit order body.

        Args:
            validity (str): `DAY` or `IOC`.
            tag (str): The caller's tag.

        Returns:
            dict: The body.
        """
        return {
            'exchange': 'NSE',
            'segment': 'NSE_EQ',
            'symbol': 'INFY',
            'transaction_type': 'BUY',
            'quantity': 5,
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price': 1415.5,
            'validity': validity,
            'tag': tag,
        }

    def print_answers(self, answers):
        """Prints each answer of a list, in request order.

        Args:
            answers (dict): Request indexes to `(body, status)` pairs.

        Returns:
            None: This method returns nothing.
        """
        for request_index in sorted(answers):
            body, status = answers[request_index]
            print(f'  [{request_index}] {status} {body["outcome"]} order_id={body["order_id"]} has intent_id={bool(body["intent_id"])}')
            if body['outcome'] == 'unknown':
                print(f'      {body["status_message"]}')

    def run(self):
        """Places the list, sends the commands and collects a hand-filled reply list.

        Returns:
            None: This method returns nothing.
        """
        market_order = {
            'exchange': 'NSE',
            'segment': 'NSE_FO',
            'underlying_symbol': 'RELIANCE',
            'expiry_date': '2026-10-27',
            'transaction_type': 'SELL',
            'quantity': 500,
            'product': 'NRML',
            'order_type': 'MARKET',
            'tag': 'slow01',
        }
        entries = [
            (
                0,
                self.limit_order('DAY', 'held01'),
                INFOSYS_ID,
            ),
            (
                1,
                self.limit_order('IOC', 'now01'),
                INFOSYS_ID,
            ),
            (
                2,
                market_order,
                RELIANCE_ID,
            ),
        ]
        print('place_many:')
        answers = self.handoff.place_many(entries, 5.0, time.perf_counter())
        for written in self.cache.stream:
            print(f'  written: request_index={written["request_index"]} tag={written["body"]["tag"]} synthetic_type={written["synthetic_type"]}')
        self.print_answers(answers)

        print('command:')
        cancel_body, cancel_status = self.handoff.command(
            'cancel_leg',
            {
                'parent_id': PARENT_ID,
                'broker': 'zerodha',
                'order_id': '250930000000001',
            },
            time.perf_counter(),
        )
        print(f'  {cancel_status} {cancel_body["outcome"]} {cancel_body["broker"]} {cancel_body["order_id"]} of parent {cancel_body["parent_id"]}')
        command_written = self.cache.stream[-1]
        print(f'  written: command={command_written["command"]} instrument_id={command_written["instrument_id"]} synthetic_type={command_written["synthetic_type"]}')

        print('command_many:')
        changes = [
            (
                0,
                'modify_leg',
                {
                    'parent_id': PARENT_ID,
                    'broker': 'zerodha',
                    'order_id': '250930000000002',
                    'price': 1414.0,
                },
            ),
            (
                1,
                'modify_leg',
                {
                    'parent_id': PARENT_ID,
                    'broker': 'zerodha',
                    'order_id': '250930000000003',
                    'quantity': 3,
                },
            ),
        ]
        change_answers = self.handoff.command_many(changes, 5.0, time.perf_counter())
        self.print_answers(change_answers)

        print('collect_replies on a list filled by hand:')
        reply_key = 'unified:orders:intents:reply:filledbyhand'
        self.cache.lists[reply_key] = [
            json.dumps({
                'request_index': 1,
                'body': {},
                'status': 200,
            }),
            'this answer cannot be read',
            json.dumps({
                'request_index': 0,
                'body': {},
                'status': 200,
            }),
        ]
        collected = self.handoff.collect_replies(reply_key, 3, 1.0)
        print(f'  collected request indexes: {sorted(collected)} of 3 owed')


if __name__ == '__main__':
    OrdersInAListAndCommandsExample().run()
