"""The order engine's loop: read an intent, place it, push the answer, acknowledge it."""

import json
import threading
import time

from unified_broker_interface.utilities.broker_orders.utilities.catalogue_availability import (
    CatalogueAvailability,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    REFRESH_SECONDS,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    ANSWER_KEY_PREFIX,
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    ORDER_UPDATES_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

GROUP = 'engine'
CONSUMER = 'order_engine'
ENTRIES_PER_READ = 10
BLOCK_MILLISECONDS = 1000
MINIMUM_BACKOFF_SECONDS = 1
MAXIMUM_BACKOFF_SECONDS = 60
DAY_ROLL_IDLE_WAIT_SECONDS = 30.0
WORKER_STOP_SECONDS = 50.0


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
        catalogue_availability (CatalogueAvailability): What turns a "not mapped" refusal into a 503 when the day's catalogue has expired and the next one is not published yet.
        placed (int): How many intents have been placed.
        refused (int): How many intents have been answered without calling a broker.
        expired (int): How many intents were too old to place.
        repeated (int): How many intents had already started a parent before they were read again.
        router (ParentRouter | None): The lanes of worker threads that place orders and own their parents, or None to do everything on the main thread.
        entries_per_read (int): How many stream entries one read takes.
        counts_lock (threading.Lock): Guards the four counts, which worker threads update.
    """

    def __init__(
        self,
        cache,
        placement,
        lock,
        logger,
        stale_intent_seconds,
        result_ttl_seconds,
        event_log=None,
        parent_store=None,
        follower=None,
        gates=None,
        ticker=None,
        price_ticker=None,
        day_roll=None,
        router=None,
        entries_per_read=ENTRIES_PER_READ,
    ):
        """Builds the engine.

        Args:
            cache (redis.Redis): The Redis client.
            placement (EnginePlacement): What turns one intent into one placed order.
            lock (EngineLock): The lock naming this process as the only engine.
            logger (logging.Logger): The logger.
            stale_intent_seconds (float): How far past its deadline an intent may be and still be placed.
            result_ttl_seconds (int): How long an answer is kept for a worker that never came back for it.
            event_log (SyntheticOrderEventLog | None): Where transitions are recorded.
            parent_store (ParentStore | None): The Redis copy of the parents.
            follower (OrderUpdateFollower | None): What applies the brokers' order updates to the legs the engine owns.
            gates (RiskGates | None): The limits every order passes.
            ticker (ClockTicker | None): What wakes the order types that are waiting for a time rather than a fill.
            price_ticker (PriceTicker | None): What hands the live quote to the order types that are watching the market.
            day_roll (DayRoll | None): What rebuilds the parent caches when they expire at 06:00 IST.
            router (ParentRouter | None): The lanes of worker threads that place orders and own their parents, or None to do everything on the main thread, one piece of work at a time.
            entries_per_read (int): How many stream entries one read takes.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.placement = placement
        self.lock = lock
        self.logger = logger
        self.stale_intent_seconds = stale_intent_seconds
        self.result_ttl_seconds = result_ttl_seconds
        self.event_log = event_log
        self.parent_store = parent_store
        self.follower = follower
        self.gates = gates
        self.ticker = ticker
        self.price_ticker = price_ticker
        self.day_roll = day_roll
        self.catalogue_availability = CatalogueAvailability(cache)
        self.placed = 0
        self.refused = 0
        self.expired = 0
        self.repeated = 0
        self.router = router
        self.entries_per_read = entries_per_read
        self.counts_lock = threading.Lock()

    def streams(self):
        """The streams this engine reads, in the order a batch is handled.

        The intents and the brokers' order updates are read in one call with one group, so a fill and a new order are noticed by the same loop and neither can starve the other. The order-update stream is the one `bin/unified/orders/websocket_order_details` already fills for the whole system, read here as a group of this engine's own.

        Returns:
            list: The stream keys.
        """
        keys = [
            INTENT_STREAM_KEY,
        ]
        if self.follower is not None:
            keys.append(ORDER_UPDATES_STREAM_KEY)
        return keys

    def ensure_group(self):
        """Creates this engine's consumer group on each stream it reads, unless it is already there.

        Both streams are created if they are missing. The engine may well start before any API worker has written an intent, and it may start before `bin/unified/orders/websocket_order_details` has seen its first order update; refusing to create the second would leave the engine failing and retrying for ever over a stream that is merely empty.

        Where the group starts differs. On the intents it starts at the beginning, because an intent written while the engine was down is an order somebody is still owed an answer for. On the order updates it starts at the end, because the retained history is tens of thousands of updates about orders placed before this engine existed, and none of them is its business. A restart resumes from the group's own position either way.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything Redis raises other than the group already existing.
        """
        for stream_key in self.streams():
            try:
                self.cache.xgroup_create(
                    stream_key,
                    GROUP,
                    id='0' if stream_key == INTENT_STREAM_KEY else '$',
                    mkstream=True,
                )
                self.logger.info(
                    f'Created consumer group {GROUP} on {stream_key}.'
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
                for stream_key, entry_id, fields in entries:
                    if stream_key == INTENT_STREAM_KEY:
                        self.take_intent(entry_id, fields)
                    else:
                        self.take_update(entry_id, fields)
                if self.follower is not None:
                    self.take_early_updates()
                # The read above blocks for about a second when nothing arrives, which is the tick
                # the time-based types need. Doing it here rather than on a thread keeps one thing
                # touching a parent at a time, so there is nothing to lock.
                if self.ticker is not None and self.ticker.due():
                    self.ticker.tick()
                if self.price_ticker is not None and self.price_ticker.due():
                    self.price_ticker.tick()
                if self.day_roll is not None and self.day_roll.due():
                    self.roll_day(stop)
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
        if self.router is not None:
            if not self.router.stop(WORKER_STOP_SECONDS):
                self.logger.warning(
                    'Some order engine workers were still busy when the '
                    'engine stopped; their unacknowledged intents are read '
                    'again at the next start.'
                )
            self.logger.info(
                f'Workers per lane: {self.router.worker_counts()}.'
            )
        followed = self.follower.followed if self.follower else 0
        self.logger.info(
            f'Stopped. Placed {self.placed}, refused {self.refused}, '
            f'expired {self.expired}, repeated {self.repeated}, '
            f'order updates followed {followed}.'
        )
        if self.follower is not None:
            self.logger.info(
                f'Early order updates: {self.follower.held} held, '
                f'{self.follower.replayed} applied once their order was known, '
                f'{self.follower.early_updates.dropped} dropped unmatched.'
            )
        if self.ticker is not None:
            self.logger.info(
                f'Clock: {self.ticker.ticks} ticks, {self.ticker.acted} '
                'parents acted on one.'
            )
        if self.price_ticker is not None:
            self.logger.info(
                f'Prices: {self.price_ticker.ticks} ticks, '
                f'{self.price_ticker.quotes_read} quotes read, '
                f'{self.price_ticker.acted} parents acted on one.'
            )
        if self.day_roll is not None and self.day_roll.rolls:
            self.logger.info(
                f'The day rolled over {self.day_roll.rolls} time(s) while '
                'this engine was running.'
            )
        if self.gates is not None:
            self.logger.info(f'Risk gates: {self.gates.counts()}.')
        return exit_code

    def read(self, pending):
        """Reads a few entries from the stream, blocking only for new ones.

        Args:
            pending (bool): True to read this consumer's unacknowledged entries instead of new ones.

        Returns:
            list: The `(stream_key, entry_id, fields)` triples read.
        """
        position = '0' if pending else '>'
        requested = {}
        for stream_key in self.streams():
            requested[stream_key] = position
        response = self.cache.xreadgroup(
            GROUP,
            CONSUMER,
            requested,
            count=self.entries_per_read,
            block=None if pending else BLOCK_MILLISECONDS,
        )
        entries = []
        for stream_key, read_entries in response or []:
            for entry_id, fields in read_entries:
                entries.append((stream_key, entry_id, fields))
        return entries

    def take_intent(self, entry_id, fields):
        """Places one intent on this thread, or hands it to a worker in the lane of the broker chosen for it.

        An intent that could not be read is acknowledged unplaced, because a poisonous entry redelivered for ever would stop every order behind it. With lanes, an intent that was already started or is too old is answered here, before a broker is chosen for it, so it takes no round-robin turn.

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
        if self.router is None:
            self.finish_intent(entry_id, intent, None)
            return
        early_answer = self.answer_without_placing(intent)
        if early_answer is not None:
            body, status = early_answer
            self.reply(intent, body, status)
            self.acknowledge(entry_id)
            return
        broker_name, skipped = self.placement.assign_broker(intent)
        worker = self.router.worker_for_new_intent(broker_name)
        worker.submit(
            self.place_on_worker,
            (
                entry_id,
                intent,
                broker_name,
                skipped,
                worker,
            ),
        )

    def place_on_worker(self, entry_id, intent, broker_name, skipped, worker):
        """Places one intent on the worker that will own its parent, sending its first legs to the broker intake chose.

        Args:
            entry_id (str): The stream entry's id.
            intent (dict): The intent document.
            broker_name (str | None): The broker intake chose, or None to let the order type choose.
            skipped (list): The brokers intake passed over, reported in the answer.
            worker (ParentWorker): This worker, which is recorded as the parent's owner.

        Returns:
            None: This method returns nothing.
        """
        self.placement.use_assignment(broker_name, skipped)
        try:
            self.finish_intent(entry_id, intent, worker)
        finally:
            self.placement.clear_assignment()

    def finish_intent(self, entry_id, intent, worker):
        """Answers one intent, pushes the answer and acknowledges it.

        An intent is acknowledged whatever happened to it, so that one failing order cannot stop every order behind it.

        Args:
            entry_id (str): The stream entry's id.
            intent (dict): The intent document.
            worker (ParentWorker | None): The worker placing it, which will own its parent, or None on the main thread.

        Returns:
            None: This method returns nothing.
        """
        try:
            body, status = self.answer(intent, worker)
        except RefusedRequestError as refusal:
            self.count_refused()
            refusal = self.catalogue_availability.explained(refusal)
            body, status = refusal.body, refusal.status
        except Exception as exception:
            self.count_refused()
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

    def count_refused(self):
        """Counts one intent answered without calling a broker.

        Returns:
            None: This method returns nothing.
        """
        with self.counts_lock:
            self.refused = self.refused + 1

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

    def answer(self, intent, worker=None):
        """Places the intent's order, unless it was already started or is too old to be worth placing.

        Args:
            intent (dict): The intent document.
            worker (ParentWorker | None): The worker placing it, recorded as the owner of the parent it creates, or None on the main thread.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        early_answer = self.answer_without_placing(intent)
        if early_answer is not None:
            return early_answer
        if self.gates is not None:
            self.gates.check_before_accepting(intent)
        started_at = time.perf_counter()
        synthetic_order = self.synthetic_order(intent)
        if self.router is not None and worker is not None:
            self.router.register(
                synthetic_order.parent.parent_order_id,
                worker,
            )
        try:
            body, status = synthetic_order.run(intent, started_at)
        except RefusedRequestError as refusal:
            synthetic_order.abandon(refusal.body.get('error'))
            raise
        with self.counts_lock:
            self.placed = self.placed + 1
        return body, status

    def answer_without_placing(self, intent):
        """The answer for an intent that must not be placed, because it already started a parent or is too old, or None for one that may be.

        Args:
            intent (dict): The intent document.

        Returns:
            tuple | None: The answer's body (dict) and its HTTP status (int), or None when the intent may be placed.
        """
        repeated_parent_id = self.started_parent_id(intent)
        if repeated_parent_id is not None:
            with self.counts_lock:
                self.repeated = self.repeated + 1
            self.logger.warning(
                f'Intent {intent.get("intent_id")} was read again after it '
                f'had already started parent {repeated_parent_id}, so it is '
                'not placed a second time.'
            )
            return {
                'error': (
                    'the order engine had already started this order before '
                    'it read it again, so it was not placed a second time; '
                    'read the parent for its outcome'
                ),
                'intent_id': intent.get('intent_id'),
                'parent_id': repeated_parent_id,
            }, 409
        expired_for = time.time() - self.expiry_moment(intent)
        if expired_for > 0:
            with self.counts_lock:
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
        return None

    def started_parent_id(self, intent):
        """The parent this intent already started, or None when it has started nothing.

        An intent is acknowledged only after its answer is pushed, so an engine that stops between sending an order and acknowledging its intent reads that intent again at its next start. Every parent is saved with its intent id before its first leg is sent, and recovery rebuilds that record from the event log, so a repeated intent is found here rather than placed twice.

        Args:
            intent (dict): The intent document.

        Returns:
            str | None: The parent order id.
        """
        intent_id = intent.get('intent_id')
        if self.parent_store is None or not intent_id:
            return None
        return self.parent_store.parent_for_intent(intent_id)

    def synthetic_order(self, intent):
        """The runner for the kind of order an intent asks for.

        Args:
            intent (dict): The intent document.

        Returns:
            SyntheticOrder: The runner, with its parent built but nothing recorded yet.

        Raises:
            RefusedRequestError: With HTTP 400 when the named type is not one the engine runs, which is a caller's mistake rather than the engine's.
        """
        named_type = intent.get('synthetic_type') or 'simple'
        synthetic_order_class = SYNTHETIC_ORDER_CLASSES.get(named_type)
        if synthetic_order_class is None:
            known_types = ', '.join(sorted(SYNTHETIC_ORDER_CLASSES))
            raise RefusedRequestError.refusal(
                f'the order engine does not run {named_type!r} orders; it runs {known_types}',
                400,
                intent_id=intent.get('intent_id'),
            )
        return synthetic_order_class.started(
            intent,
            self.placement,
            self.event_log,
            self.parent_store,
            self.logger,
            self.gates,
        )

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
        """Pushes the answer onto the key the waiting API worker is blocked on, and stores it under the intent's id.

        An intent that came in a list is answered on the list's shared key, so its answer names its place in the list. The stored copy is what `GET /api/orders/intents/<intent_id>` reads for a caller who stopped waiting. It is written only if none is there yet, so a repeated intent's 409 cannot replace the answer the first reading gave.

        Args:
            intent (dict): The intent document.
            body (dict): The answer's body.
            status (int): The answer's HTTP status.

        Returns:
            None: This method returns nothing.
        """
        stored = json.dumps({
            'body': body,
            'status': status,
        })
        pushed = {
            'body': body,
            'status': status,
        }
        if intent.get('request_index') is not None:
            pushed['request_index'] = intent['request_index']
            pushed['intent_id'] = intent.get('intent_id')
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.rpush(intent['reply_key'], json.dumps(pushed))
        pipeline.expire(intent['reply_key'], self.result_ttl_seconds)
        if intent.get('intent_id'):
            pipeline.set(
                ANSWER_KEY_PREFIX + intent['intent_id'],
                stored,
                nx=True,
                ex=self.result_ttl_seconds,
            )
        pipeline.execute()

    def take_update(self, entry_id, fields):
        """Applies one broker order update here, or hands it to the worker that owns its parent.

        With lanes, an update whose order no parent owns yet is held by the follower and acknowledged, exactly as without them.

        Args:
            entry_id (str): The stream entry's id.
            fields (dict): The stream entry's fields.

        Returns:
            None: This method returns nothing.
        """
        if self.router is None:
            self.apply_update(entry_id, fields)
            return
        parent_order_id, broker_name = self.follower.owning_parent(fields)
        if parent_order_id is None:
            self.acknowledge(entry_id, ORDER_UPDATES_STREAM_KEY)
            return
        self.router.route(
            parent_order_id,
            broker_name,
            self.apply_update,
            (
                entry_id,
                fields,
            ),
        )

    def apply_update(self, entry_id, fields):
        """Applies one broker order update to the leg it belongs to, if the engine owns one.

        Most updates on that stream belong to orders placed somewhere else entirely, so an update that names no leg of ours is acknowledged and dropped. A failure to apply one is logged and the entry acknowledged: the broker's own book is read on the next start, so a lost update costs accuracy until then rather than correctness.

        Args:
            entry_id (str): The stream entry's id.
            fields (dict): The stream entry's fields.

        Returns:
            None: This method returns nothing.
        """
        try:
            parent = self.follower.follow(fields)
            if parent is not None:
                self.parent_store.save(parent)
        except Exception:
            self.logger.exception(
                f'The order update in stream entry {entry_id} could not be '
                'applied; the broker book is read again at the next start.'
            )
        self.acknowledge(entry_id, ORDER_UPDATES_STREAM_KEY)

    def take_early_updates(self):
        """Applies the held order updates whose order is now known, here or on the workers that own their parents.

        Returns:
            None: This method returns nothing.
        """
        if self.router is None:
            self.replay_early_updates()
            return
        try:
            taken = self.follower.take_known_early_updates()
        except Exception:
            self.logger.exception(
                'Order updates held for an order the engine did not know yet '
                'could not be looked up; they are tried again after the next '
                'read.'
            )
            return
        for parent_order_id, broker_name, fields in taken:
            self.router.route(
                parent_order_id,
                broker_name,
                self.apply_replayed_update,
                (fields,),
            )

    def apply_replayed_update(self, fields):
        """Applies one held order update on the worker that owns its parent.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            None: This method returns nothing.
        """
        try:
            parent = self.follower.follow(fields)
            if parent is not None:
                self.follower.count_replayed()
                self.parent_store.save(parent)
        except Exception:
            self.logger.exception(
                'A held order update could not be applied; the broker book '
                'is read again at the next start.'
            )

    def roll_day(self, stop):
        """Rebuilds the parent caches at 06:00 IST, once no worker is changing a parent.

        Nothing new reaches a worker while this waits, because only this thread hands out work. Every parent's owner is forgotten after the rebuild, and a parent still open is given an owner again when its next piece of work arrives.

        Args:
            stop (threading.Event): Set when the engine is stopping.

        Returns:
            None: This method returns nothing.
        """
        if self.router is not None:
            idle = self.router.wait_until_idle(
                stop,
                DAY_ROLL_IDLE_WAIT_SECONDS,
            )
            if not idle:
                self.logger.warning(
                    'The day rolled over while workers were still busy, so '
                    'the parent caches are rebuilt on a later pass.'
                )
                return
        self.day_roll.roll()
        if self.router is not None:
            self.router.forget_owners()

    def replay_early_updates(self):
        """Applies the order updates that arrived before their order was known, now that it may be.

        A failure is logged rather than raised, for the same reason `handle_update` logs one: the broker's own book is read again at the next start, so a lost update costs accuracy until then rather than correctness.

        Returns:
            None: This method returns nothing.
        """
        try:
            for parent in self.follower.replay_early_updates():
                self.parent_store.save(parent)
        except Exception:
            self.logger.exception(
                'Order updates held for an order the engine did not know yet '
                'could not be applied; the broker book is read again at the '
                'next start.'
            )

    def acknowledge(self, entry_id, stream_key=INTENT_STREAM_KEY):
        """Acknowledges one stream entry, so it is not redelivered.

        Args:
            entry_id (str): The stream entry's id.
            stream_key (str): The stream it came from.

        Returns:
            None: This method returns nothing.
        """
        self.cache.xack(stream_key, GROUP, entry_id)
