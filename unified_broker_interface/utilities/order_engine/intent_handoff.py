"""Handing one accepted order to the order engine, and waiting for the answer it sends back."""

import json
import time

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.order_intent import OrderIntent

INTENT_STREAM_KEY = 'unified:orders:intents:stream'
INTENT_STREAM_FIELD = 'intent'
STREAM_MAX_LENGTH = 10000


class IntentHandoff:
    """Writes an accepted order to the intent stream and blocks until the engine answers it.

    The caller's contract does not change. `POST /api/orders/place` still answers one request with one body, so the worker waits rather than answering immediately with something to poll. What it costs is one Redis connection held for as long as the engine takes, which is the same shape as holding one broker connection for as long as the broker takes.

    Attributes:
        cache (redis.Redis): The Redis client.
        timeout_seconds (float): How long to wait for the engine before answering that the outcome is unknown.
    """

    def __init__(self, cache, timeout_seconds):
        """Builds the handoff.

        Args:
            cache (redis.Redis): The Redis client.
            timeout_seconds (float): How long to wait for the engine's answer.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.timeout_seconds = timeout_seconds

    def place(self, body, started_at):
        """Writes the order down for the engine and answers with what the engine did.

        Args:
            body (dict | None): The caller's decoded JSON body, already validated.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be written or read.
        """
        intent = OrderIntent(body, self.timeout_seconds)
        try:
            self.cache.xadd(
                INTENT_STREAM_KEY,
                {
                    INTENT_STREAM_FIELD: json.dumps(intent.document()),
                },
                maxlen=STREAM_MAX_LENGTH,
                approximate=True,
            )
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'the order could not be written for the order engine: {error}',
                503,
            )

        try:
            reply = self.cache.blpop(intent.reply_key, timeout=self.timeout_seconds)
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'the order engine was written to but its answer could not be read: {error}',
                503,
                intent_id=intent.intent_id,
            )
        if reply is None:
            return self.timed_out_answer(intent, started_at)
        return self.engine_answer(intent, reply[1], started_at)

    def engine_answer(self, intent, reply_text, started_at):
        """Reads the engine's answer and corrects the one timing the engine could not measure.

        The engine's `preparation` is measured on the engine's own clock and cannot be compared with this worker's, so it is replaced. What the caller is told `preparation` means does not change: the API's own work before the request left the machine. In engine mode that work now includes the queue hop and the engine's own preparation, which is correct, because all of it happened before the request left.

        Args:
            intent (OrderIntent): The intent this answers.
            reply_text (str): The answer document the engine pushed.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 504 when the engine's answer cannot be read, because an unreadable answer does not mean the order was not placed.
        """
        try:
            reply = json.loads(reply_text)
        except ValueError:
            reply = None
        if not isinstance(reply, dict) or not isinstance(reply.get('body'), dict):
            raise RefusedRequestError.refusal(
                'the order engine answered with something that could not be read, so the outcome of this order is unknown',
                504,
                intent_id=intent.intent_id,
            )
        body = reply['body']
        status = reply.get('status')
        if not isinstance(status, int):
            status = 504
        body['intent_id'] = intent.intent_id
        self.correct_preparation(body, started_at)
        return body, status

    def correct_preparation(self, body, started_at):
        """Replaces the engine's `preparation` with the time this worker measured.

        A refusal carries no timings at all, and a dry run carries no broker time, so both are left with whatever they have beside a `preparation` measured here.

        Args:
            body (dict): The answer's body, changed in place.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            None: This method returns nothing.
        """
        timings = body.get('timing_ms')
        if not isinstance(timings, dict):
            return
        total_milliseconds = (time.perf_counter() - started_at) * 1000
        broker_milliseconds = timings.get('broker')
        if isinstance(broker_milliseconds, (int, float)):
            total_milliseconds = total_milliseconds - broker_milliseconds
        timings['preparation'] = round(total_milliseconds, 3)

    def timed_out_answer(self, intent, started_at):
        """Answers that the outcome is unknown, because the engine may still place the order.

        The engine refuses to place an intent whose deadline has long passed, so the order does not arrive at the broker much later than the caller expected. Between the deadline and that refusal, though, the order may well be sent, and an answer claiming otherwise would be a lie the caller could act on.

        Args:
            intent (OrderIntent): The intent that was not answered.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is always 504.
        """
        preparation_milliseconds = (time.perf_counter() - started_at) * 1000
        return {
            'broker': None,
            'instrument_id': None,
            'tag': intent.body.get('tag'),
            'outcome': 'unknown',
            'order_id': None,
            'status_message': f'the order engine did not answer within {self.timeout_seconds} seconds, so this order may still be placed',
            'broker_response': None,
            'skipped': [],
            'intent_id': intent.intent_id,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
            },
        }, 504
