"""The order engine's loop: read an intent, place it, push the answer, acknowledge it."""

import json
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    REFRESH_SECONDS,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)

GROUP = 'engine'
CONSUMER = 'order_engine'
ENTRIES_PER_READ = 10
BLOCK_MILLISECONDS = 1000
MINIMUM_BACKOFF_SECONDS = 1
MAXIMUM_BACKOFF_SECONDS = 60


class OrderEngine:
    """Reads the intent stream and places every order the REST API accepts.

    The engine takes its own consumer group on the stream, `engine`, as every other consumer in this project takes one of its own.

    An intent is acknowledged once its answer has been pushed, not before. An intent read but never acknowledged is redelivered at the next start, which is the pending-first read below, and is where the deadline check earns its place: an order abandoned by a worker hours ago must not be sent into a market that has moved.

    Attributes:
        cache (redis.Redis): The Redis client.
        placement (EnginePlacement): What turns one intent into one placed order.
        lock (EngineLock): The lock naming this process as the only engine.
        logger (logging.Logger): The logger.
        stale_intent_seconds (float): How far past its deadline an intent may be and still be placed.
        result_ttl_seconds (int): How long an answer is kept for a worker that never came back for it.
        placed (int): How many intents have been placed.
        refused (int): How many intents have been answered without calling a broker.
        expired (int): How many intents were too old to place.
    """

    def __init__(
        self,
        cache,
        placement,
        lock,
        logger,
        stale_intent_seconds,
        result_ttl_seconds,
    ):
        """Builds the engine.

        Args:
            cache (redis.Redis): The Redis client.
            placement (EnginePlacement): What turns one intent into one placed order.
            lock (EngineLock): The lock naming this process as the only engine.
            logger (logging.Logger): The logger.
            stale_intent_seconds (float): How far past its deadline an intent may be and still be placed.
            result_ttl_seconds (int): How long an answer is kept for a worker that never came back for it.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.placement = placement
        self.lock = lock
        self.logger = logger
        self.stale_intent_seconds = stale_intent_seconds
        self.result_ttl_seconds = result_ttl_seconds
        self.placed = 0
        self.refused = 0
        self.expired = 0

    def ensure_group(self):
        """Creates the consumer group at the start of the stream, creating the stream too, unless it exists.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything Redis raises other than the group already existing.
        """
        try:
            self.cache.xgroup_create(
                INTENT_STREAM_KEY,
                GROUP,
                id='0',
                mkstream=True,
            )
            self.logger.info(
                f'Created consumer group {GROUP} on {INTENT_STREAM_KEY}.'
            )
        except Exception as exception:
            if 'BUSYGROUP' not in str(exception):
                raise

    def run(self, stop):
        """Places orders until `stop` is set or the lock is lost.

        Args:
            stop (threading.Event): Set to ask the engine to finish the intent in hand and stop.

        Returns:
            int: The exit code: 0 when stopped cleanly, and 1 when the lock was lost to another engine.
        """
        backoff = MINIMUM_BACKOFF_SECONDS
        pending_first = True
        refreshed_at = time.monotonic()
        exit_code = 0
        while not stop.is_set():
            try:
                if time.monotonic() - refreshed_at >= REFRESH_SECONDS:
                    if not self.lock.refresh():
                        exit_code = 1
                        break
                    refreshed_at = time.monotonic()

                if pending_first:
                    self.ensure_group()
                    entries = self.read(True)
                    if not entries:
                        pending_first = False
                else:
                    entries = self.read(False)
                for entry_id, fields in entries:
                    self.handle(entry_id, fields)
                backoff = MINIMUM_BACKOFF_SECONDS
            except Exception as exception:
                self.logger.error(
                    f'The order engine failed, retrying in {backoff} seconds: '
                    f'{type(exception).__name__}: {exception}'
                )
                pending_first = True
                if stop.is_set():
                    break
                stop.wait(backoff)
                backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)
        self.logger.info(
            f'Stopped. Placed {self.placed}, refused {self.refused}, '
            f'expired {self.expired}.'
        )
        return exit_code

    def read(self, pending):
        """Reads a few entries from the stream, blocking only for new ones.

        Args:
            pending (bool): True to read this consumer's unacknowledged entries instead of new ones.

        Returns:
            list: The `(entry_id, fields)` pairs read.
        """
        response = self.cache.xreadgroup(
            GROUP,
            CONSUMER,
            {
                INTENT_STREAM_KEY: '0' if pending else '>',
            },
            count=ENTRIES_PER_READ,
            block=None if pending else BLOCK_MILLISECONDS,
        )
        entries = []
        for _, read_entries in response or []:
            entries.extend(read_entries)
        return entries

    def handle(self, entry_id, fields):
        """Places one intent, pushes its answer and acknowledges it.

        An intent is acknowledged whatever happened to it, including when it could not be read at all, because a poisonous entry redelivered for ever would stop every order behind it.

        Args:
            entry_id (str): The stream entry's id.
            fields (dict): The stream entry's fields.

        Returns:
            None: This method returns nothing.
        """
        intent = self.decode(fields)
        if intent is None:
            self.logger.error(
                f'The intent in stream entry {entry_id} could not be read, so '
                'it is being acknowledged unplaced.'
            )
            self.acknowledge(entry_id)
            return
        try:
            body, status = self.answer(intent)
        except RefusedRequestError as refusal:
            self.refused = self.refused + 1
            body, status = refusal.body, refusal.status
        except Exception as exception:
            self.refused = self.refused + 1
            self.logger.exception(
                f'Intent {intent.get("intent_id")} could not be placed.'
            )
            body = {
                'error': (
                    'the order engine failed while placing this order '
                    f'({type(exception).__name__}), so its outcome is unknown'
                ),
            }
            status = 504
        self.reply(intent, body, status)
        self.acknowledge(entry_id)

    def decode(self, fields):
        """Reads one stream entry's intent document.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            dict | None: The intent, or None when the entry does not hold one.
        """
        try:
            intent = json.loads((fields or {}).get(INTENT_STREAM_FIELD))
        except (TypeError, ValueError):
            return None
        if not isinstance(intent, dict) or not intent.get('reply_key'):
            return None
        return intent

    def answer(self, intent):
        """Places the intent's order, unless it is too old to be worth placing.

        Args:
            intent (dict): The intent document.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        expired_for = time.time() - self.expiry_moment(intent)
        if expired_for > 0:
            self.expired = self.expired + 1
            self.logger.warning(
                f'Intent {intent.get("intent_id")} passed its deadline '
                f'{expired_for:.1f} seconds ago, so it is recorded rather '
                'than placed.'
            )
            return {
                'error': (
                    'the order engine read this order after the caller had '
                    'stopped waiting for it, so it was not placed'
                ),
                'intent_id': intent.get('intent_id'),
                'expired_seconds': round(expired_for, 3),
            }, 409
        intent['engine_started_at'] = time.perf_counter()
        body, status = self.placement.place(intent)
        self.placed = self.placed + 1
        return body, status

    def expiry_moment(self, intent):
        """The Unix time after which an intent is too old to place.

        Args:
            intent (dict): The intent document.

        Returns:
            float: The moment, which is the deadline the API worker wrote plus the configured grace.
        """
        deadline_at = intent.get('deadline_at')
        if not isinstance(deadline_at, (int, float)):
            deadline_at = intent.get('created_at')
        if not isinstance(deadline_at, (int, float)):
            return float('inf')
        return deadline_at + self.stale_intent_seconds

    def reply(self, intent, body, status):
        """Pushes the answer onto the key the waiting API worker is blocked on.

        Args:
            intent (dict): The intent document.
            body (dict): The answer's body.
            status (int): The answer's HTTP status.

        Returns:
            None: This method returns nothing.
        """
        document = json.dumps({
            'body': body,
            'status': status,
        })
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.rpush(intent['reply_key'], document)
        pipeline.expire(intent['reply_key'], self.result_ttl_seconds)
        pipeline.execute()

    def acknowledge(self, entry_id):
        """Acknowledges one stream entry, so it is not redelivered.

        Args:
            entry_id (str): The stream entry's id.

        Returns:
            None: This method returns nothing.
        """
        self.cache.xack(INTENT_STREAM_KEY, GROUP, entry_id)
