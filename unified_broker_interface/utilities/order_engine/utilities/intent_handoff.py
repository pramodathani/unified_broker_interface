"""Handing one accepted order to the order engine, and waiting for the answer it sends back."""

import json
import time
import uuid

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import LOCK_KEY
from unified_broker_interface.utilities.order_engine.utilities.order_intent import OrderIntent

INTENT_STREAM_KEY = 'unified:orders:intents:stream'
INTENT_STREAM_FIELD = 'intent'
STREAM_MAX_LENGTH = 10000
LIST_REPLY_KEY_PREFIX = 'unified:orders:intents:reply:'
ANSWER_KEY_PREFIX = 'unified:orders:intents:answer:'


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

    def place(self, body, instrument_id, started_at):
        """Writes the order down for the engine and answers with what the engine did.

        The instrument is resolved by the API worker rather than the engine, so the rule that decides an identity is unknown or ambiguous lives in one place. The engine still reads that instrument's catalogue entry itself, because it needs the handles and the contract size at the moment it places each leg.

        Args:
            body (dict | None): The caller's decoded JSON body, already validated.
            instrument_id (str): The instrument the order is for, already resolved.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when the order engine is not running or the order cannot be written for it.
        """
        self.refuse_unless_engine_running()
        intent = OrderIntent(body, instrument_id, self.timeout_seconds)
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
            return self.unknown_answer(
                intent,
                started_at,
                f'the order was written for the order engine but its answer could not be read ({error}), so this order may still be placed',
            )
        if reply is None:
            return self.unknown_answer(
                intent,
                started_at,
                f'the order engine did not answer within {self.timeout_seconds} seconds, so this order may still be placed',
            )
        return self.engine_answer(intent, reply[1], started_at)

    def place_many(self, entries, wait_seconds, started_at):
        """Writes several orders for the engine in one round trip and collects each one's answer.

        Every intent names the same reply list and its own place in the request, so one list carries every answer back, in whatever order the engine's workers finish. The wait stops when every order has an answer or `wait_seconds` has passed. An order without an answer by then is answered as outcome `unknown` with its `intent_id`, because the engine may still place it, and its answer can be read later from `GET /api/orders/intents/<intent_id>`.

        Args:
            entries (list): One `(request_index, body, instrument_id)` triple per order, each body already validated and each instrument already resolved.
            wait_seconds (float): The longest to wait for the answers.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            dict: Each request index (int) to a tuple of the order's answer body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when the order engine is not running or Redis cannot be read before anything is written.
        """
        self.refuse_unless_engine_running()
        reply_key = LIST_REPLY_KEY_PREFIX + uuid.uuid4().hex
        intents = {}
        for request_index, body, instrument_id in entries:
            intents[request_index] = OrderIntent(
                body,
                instrument_id,
                wait_seconds,
                request_index,
                reply_key,
            )
        return self.hand_over_many(intents, reply_key, wait_seconds, started_at)

    def command(self, command, arguments, started_at):
        """Hands one change to a parent the engine owns to the worker that owns it, and answers with what it did.

        Args:
            command (str): The command, such as `cancel_leg` or `modify_leg`.
            arguments (dict): The command's arguments, such as `parent_id`, `broker` and `order_id`.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when the order engine is not running or the command cannot be written for it.
        """
        answers = self.command_many(
            [
                (0, command, arguments),
            ],
            self.timeout_seconds,
            started_at,
        )
        return answers[0]

    def command_many(self, entries, wait_seconds, started_at):
        """Hands several changes to parents the engine owns over in one round trip, and collects each one's answer.

        Args:
            entries (list): One `(request_index, command, arguments)` triple per change.
            wait_seconds (float): The longest to wait for the answers.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            dict: Each request index (int) to a tuple of the change's answer body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when the order engine is not running or Redis cannot be read before anything is written.
        """
        self.refuse_unless_engine_running()
        reply_key = LIST_REPLY_KEY_PREFIX + uuid.uuid4().hex
        intents = {}
        for request_index, command, arguments in entries:
            intents[request_index] = OrderIntent(
                arguments,
                None,
                wait_seconds,
                request_index,
                reply_key,
                command,
            )
        return self.hand_over_many(intents, reply_key, wait_seconds, started_at)

    def hand_over_many(self, intents, reply_key, wait_seconds, started_at):
        """Writes several intents in one pipeline and collects each one's answer from their shared reply list.

        Args:
            intents (dict): Each request index (int) to its `OrderIntent`, all naming `reply_key`.
            reply_key (str): The list the engine answers every intent on.
            wait_seconds (float): The longest to wait for the answers.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            dict: Each request index (int) to a tuple of the answer's body (dict) and its HTTP status (int).
        """
        pipeline = self.cache.pipeline(transaction=False)
        for intent in intents.values():
            pipeline.xadd(
                INTENT_STREAM_KEY,
                {
                    INTENT_STREAM_FIELD: json.dumps(intent.document()),
                },
                maxlen=STREAM_MAX_LENGTH,
                approximate=True,
            )
        answers = {}
        try:
            pipeline.execute()
        except redis.RedisError as error:
            for request_index, intent in intents.items():
                answers[request_index] = self.unknown_answer(
                    intent,
                    started_at,
                    f'the requests could not all be written for the order engine ({error}), so this one may or may not have been made',
                )
            return answers
        reply_texts = self.collect_replies(reply_key, len(intents), wait_seconds)
        for request_index, intent in intents.items():
            reply_text = reply_texts.get(request_index)
            if reply_text is None:
                answers[request_index] = self.unknown_answer(
                    intent,
                    started_at,
                    f'the order engine did not answer within {wait_seconds} seconds, so this may still happen; read its answer later by its intent_id',
                )
                continue
            try:
                answers[request_index] = self.engine_answer(
                    intent,
                    reply_text,
                    started_at,
                )
            except RefusedRequestError as refusal:
                answers[request_index] = (refusal.body, refusal.status)
        return answers

    def collect_replies(self, reply_key, expected_count, wait_seconds):
        """Takes answers off one request's reply list until every order has one or the wait runs out.

        Args:
            reply_key (str): The request's reply list.
            expected_count (int): How many answers are owed.
            wait_seconds (float): The longest to wait in all.

        Returns:
            dict: Each request index (int) to the answer document the engine pushed (str); an order not answered in time is left out.
        """
        deadline = time.monotonic() + wait_seconds
        reply_texts = {}
        while len(reply_texts) < expected_count:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            try:
                reply = self.cache.blpop(reply_key, timeout=remaining_seconds)
            except redis.RedisError:
                break
            if reply is None:
                break
            try:
                request_index = json.loads(reply[1]).get('request_index')
            except (AttributeError, ValueError):
                continue
            if isinstance(request_index, int):
                reply_texts[request_index] = reply[1]
        return reply_texts

    def stored_answer(self, intent_id):
        """The answer the engine stored for one intent, for a caller who stopped waiting before it came.

        Args:
            intent_id (str): The intent's id.

        Returns:
            tuple | None: The answer's body (dict) and its HTTP status (int), or None when no answer is stored, because the engine has not answered yet, the intent is unknown, or the answer has expired.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read.
        """
        try:
            stored = self.cache.get(ANSWER_KEY_PREFIX + intent_id)
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
            )
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict) or not isinstance(document.get('body'), dict):
            return None
        status = document.get('status')
        if not isinstance(status, int):
            status = 504
        body = document['body']
        body['intent_id'] = intent_id
        return body, status

    def refuse_unless_engine_running(self):
        """Refuses the order before it is written down when no order engine holds its lock.

        A running engine refreshes `unified:orders:engine:lock` every few seconds and the key expires by itself soon after the engine stops. Without this check an order written while no engine runs would wait out the whole timeout and be answered as `unknown`, although nothing was ever going to place it.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when no engine holds the lock or Redis cannot be read.
        """
        try:
            engine_running = self.cache.exists(LOCK_KEY)
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
            )
        if not engine_running:
            raise RefusedRequestError.refusal(
                'the order engine is not running, so the order was not placed; start unified-orders@order_engine.service',
                503,
            )

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

    def unknown_answer(self, intent, started_at, status_message):
        """Answers that the outcome is unknown, because the engine may still place the order.

        Every way of failing after the intent has been written ends here: a wait that ran out, and a Redis that stopped answering while the wait was on. In both the order is already on the stream, so it may be placed, and only an answer that says the outcome is unknown is one the caller cannot be misled by. A refusal with HTTP 503 would say the opposite, that nothing happened.

        The engine keeps the other half of this promise. It refuses to place an intent whose deadline passed more than `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` ago, so an order abandoned here cannot arrive at the broker much later than the caller expected.

        Args:
            intent (OrderIntent): The intent that was not answered.
            started_at (float): `time.perf_counter()` when the request arrived.
            status_message (str): Why the outcome is unknown.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is always 504.
        """
        preparation_milliseconds = (time.perf_counter() - started_at) * 1000
        return {
            'broker': None,
            'instrument_id': intent.instrument_id,
            'tag': intent.body.get('tag'),
            'outcome': 'unknown',
            'order_id': None,
            'status_message': status_message,
            'broker_response': None,
            'skipped': [],
            'intent_id': intent.intent_id,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
            },
        }, 504
