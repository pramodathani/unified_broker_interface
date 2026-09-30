"""Hands one accepted order to the order engine and reads back the answer the engine gives.

`POST /api/orders/place` does not call a broker itself. Once it has validated the body and resolved the instrument, it builds an `IntentHandoff` and calls `place`, which first checks that an engine holds its lock, then writes the order to `unified:orders:intents:stream` and blocks on the order's own reply list until the engine pushes its answer. The engine also stores the answer under the intent's id, so a caller who stopped waiting can read it later through `stored_answer`.

The program replaces Redis with `PretendEngineRedis`, a stand-in whose `blpop` plays the engine: before it looks at a reply list, it answers every intent written since it last looked with a Zerodha order id, exactly in the shape the engine's own `reply` pushes. No real engine, broker or Redis is involved, and nothing is placed.

The intent id is a fresh random UUID on every run, so the program prints whether the answer carries the id of the intent that was written rather than the id itself. The engine's `preparation` time is measured on the engine's clock, so the handoff replaces it with the time measured in this process; the program shows that the engine's value was replaced but not the new value, which changes from run to run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/intent_handoff/IntentHandoff/example_1_placing_one_order.py
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


class PlacingOneOrderExample:
    """Places one limit order through the handoff and reads its answer twice.

    Attributes:
        cache (PretendEngineRedis): The stand-in Redis client with its pretend engine.
        handoff (IntentHandoff): The handoff being shown.
    """

    def __init__(self):
        """Builds the handoff over the stand-in, waiting at most ten seconds for an answer.

        Returns:
            None: This method returns nothing.
        """
        self.cache = PretendEngineRedis()
        self.handoff = IntentHandoff(self.cache, 10.0)

    def run(self):
        """Places the order, prints the intent written and the answer, then reads the stored answer.

        Returns:
            None: This method returns nothing.
        """
        self.handoff.refuse_unless_engine_running()
        print('an engine holds its lock, so the order can be handed over')

        body = {
            'exchange': 'NSE',
            'segment': 'NSE_EQ',
            'symbol': 'INFY',
            'transaction_type': 'BUY',
            'quantity': 10,
            'product': 'CNC',
            'order_type': 'LIMIT',
            'price': 1415.5,
            'tag': 'swing01',
        }
        answer_body, status = self.handoff.place(body, INFOSYS_ID, time.perf_counter())

        written = self.cache.stream[0]
        print(f'intents on the stream: {len(self.cache.stream)}')
        print(f'written synthetic_type: {written["synthetic_type"]}')
        print(f'written instrument_id: {written["instrument_id"]}')
        own_reply_key = 'unified:orders:intents:result:' + written['intent_id']
        print(f'written reply_key is the intent\'s own list: {written["reply_key"] == own_reply_key}')
        print(f'written body: {written["body"]}')

        print(f'status: {status}')
        print(f'broker: {answer_body["broker"]}, outcome: {answer_body["outcome"]}, order_id: {answer_body["order_id"]}, tag: {answer_body["tag"]}')
        print(f'answer carries the written intent_id: {answer_body["intent_id"] == written["intent_id"]}')
        print(f'engine preparation replaced: {answer_body["timing_ms"]["preparation"] != 0.25}')
        print(f'broker time kept: {answer_body["timing_ms"]["broker"]}')

        stored = self.handoff.stored_answer(written['intent_id'])
        stored_body, stored_status = stored
        print(f'stored answer: status {stored_status}, order_id {stored_body["order_id"]}, key {ANSWER_KEY_PREFIX}<intent_id>')
        print(f'stored answer for an intent nobody wrote: {self.handoff.stored_answer("0" * 32)}')


if __name__ == '__main__':
    PlacingOneOrderExample().run()
