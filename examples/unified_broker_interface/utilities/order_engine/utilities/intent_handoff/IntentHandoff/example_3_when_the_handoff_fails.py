"""Shows how the handoff answers when the order engine is not running, when Redis fails mid-request and when the engine's answer cannot be read.

The handoff answers differently depending on whether the order has already been written for the engine. Before anything is written, the honest answer is a refusal: `refuse_unless_engine_running` raises `RefusedRequestError` with HTTP 503 when no engine holds `unified:orders:engine:lock`, and nothing was placed. After an intent is written, the order may still be placed, so every failure becomes outcome `unknown` with HTTP 504 through `unknown_answer`, never a 503 that would tell the caller nothing happened.

The program builds three handoffs over `UnreliableRedis`, a stand-in Redis client that can pretend the engine is stopped and can fail the pipeline that writes intents with the same `redis.ConnectionError` a dropped connection raises. It also calls `engine_answer` with text that is not JSON, which the handoff refuses with 504, and `correct_preparation` on a body with and without timings, to show that only an answer carrying timings has its `preparation` replaced.

Timings are measured on this machine's clock and change from run to run, so the program prints which timing keys an answer has rather than their values.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/intent_handoff/IntentHandoff/example_3_when_the_handoff_fails.py
"""

import time

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    IntentHandoff,
)
from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)

INFOSYS_ID = '11111111-1111-5111-8111-000000000001'


class UnreliableRedis:
    """A stand-in for the Redis client that can pretend the engine is stopped and that writes fail.

    Attributes:
        engine_running (bool): Whether the engine's lock key exists.
        writes_fail (bool): Whether executing a pipeline raises `redis.ConnectionError`.
    """

    def __init__(self, engine_running, writes_fail):
        """Builds the stand-in.

        Args:
            engine_running (bool): Whether the engine's lock key exists.
            writes_fail (bool): Whether executing a pipeline raises `redis.ConnectionError`.

        Returns:
            None: This method returns nothing.
        """
        self.engine_running = engine_running
        self.writes_fail = writes_fail

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

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Accepted and ignored.

        Returns:
            UnreliablePipeline: The pipeline.
        """
        del transaction
        return UnreliablePipeline(self.writes_fail)


class UnreliablePipeline:
    """A stand-in for a Redis pipeline whose `execute` may fail.

    Attributes:
        writes_fail (bool): Whether `execute` raises.
        queued (int): How many writes were queued.
    """

    def __init__(self, writes_fail):
        """Builds an empty pipeline.

        Args:
            writes_fail (bool): Whether `execute` raises.

        Returns:
            None: This method returns nothing.
        """
        self.writes_fail = writes_fail
        self.queued = 0

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Queues one stream write.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.
            maxlen (int | None): Accepted and ignored.
            approximate (bool): Accepted and ignored.

        Returns:
            None: This method returns nothing.
        """
        del key, fields, maxlen, approximate
        self.queued = self.queued + 1

    def execute(self):
        """Sends the queued writes, or fails as a dropped connection would.

        Returns:
            list: One entry id per queued write.

        Raises:
            redis.ConnectionError: When the pipeline was built to fail.
        """
        if self.writes_fail:
            raise redis.ConnectionError('Connection closed by server.')
        entry_ids = []
        for position in range(self.queued):
            entry_ids.append(f'{position + 1}-0')
        return entry_ids


class WhenTheHandoffFailsExample:
    """Runs the handoff into each failure in turn and prints the answer it gives.

    Attributes:
        body (dict): The order every attempt hands over.
    """

    def __init__(self):
        """Builds the order body.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'exchange': 'NSE',
            'segment': 'NSE_EQ',
            'symbol': 'INFY',
            'transaction_type': 'SELL',
            'quantity': 10,
            'product': 'CNC',
            'order_type': 'MARKET',
            'tag': 'exit02',
        }

    def run(self):
        """Prints the answer to each failure.

        Returns:
            None: This method returns nothing.
        """
        stopped = IntentHandoff(UnreliableRedis(False, False), 10.0)
        print('--- no engine running')
        try:
            stopped.place(self.body, INFOSYS_ID, time.perf_counter())
        except RefusedRequestError as refusal:
            print(f'{refusal.status}: {refusal.body["error"]}')

        print('--- Redis fails while the list is written')
        failing = IntentHandoff(UnreliableRedis(True, True), 10.0)
        failing.refuse_unless_engine_running()
        reply_key = 'unified:orders:intents:reply:failedwrite'
        intents = {
            0: OrderIntent(self.body, INFOSYS_ID, 5.0, 0, reply_key),
            1: OrderIntent(self.body, INFOSYS_ID, 5.0, 1, reply_key),
        }
        answers = failing.hand_over_many(intents, reply_key, 5.0, time.perf_counter())
        for request_index in sorted(answers):
            answer_body, status = answers[request_index]
            print(f'[{request_index}] {status} {answer_body["outcome"]}: {answer_body["status_message"]}')
            print(f'    intent_id is the intent\'s own: {answer_body["intent_id"] == intents[request_index].intent_id}, timings: {sorted(answer_body["timing_ms"])}')

        print('--- the engine answers with something unreadable')
        intent = OrderIntent(self.body, INFOSYS_ID, 10.0)
        try:
            failing.engine_answer(intent, 'not a json document', time.perf_counter())
        except RefusedRequestError as refusal:
            print(f'{refusal.status}: {refusal.body["error"]}')
            print(f'refusal names the intent: {refusal.body["intent_id"] == intent.intent_id}')

        print('--- unknown_answer on its own')
        unknown_body, unknown_status = failing.unknown_answer(
            intent,
            time.perf_counter(),
            'the engine stopped answering',
        )
        print(f'{unknown_status} outcome={unknown_body["outcome"]} broker={unknown_body["broker"]} tag={unknown_body["tag"]} skipped={unknown_body["skipped"]}')

        print('--- correct_preparation')
        placed = {
            'outcome': 'accepted',
            'timing_ms': {
                'preparation': 0.25,
                'broker': 38.2,
            },
        }
        failing.correct_preparation(placed, time.perf_counter())
        print(f'placed answer: preparation replaced {placed["timing_ms"]["preparation"] != 0.25}, broker kept {placed["timing_ms"]["broker"]}')
        refused = {
            'error': 'no broker can take this order',
        }
        failing.correct_preparation(refused, time.perf_counter())
        print(f'refusal left as it was: {refused}')


if __name__ == '__main__':
    WhenTheHandoffFailsExample().run()
