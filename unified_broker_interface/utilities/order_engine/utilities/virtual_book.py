"""Keeping every held virtual limit order's queue estimate up to date from the unified quote stream."""

import json
import time

import redis

from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)

ESTIMATES_KEY = 'unified:orders:virtual_queue'
QUOTES_STREAM_KEY = 'unified:quotes:stream'
VIRTUAL_LIMIT_TYPE = 'virtual_limit'
READ_COUNT = 1000
BLOCK_MILLISECONDS = 1000
REFRESH_SECONDS = 2.0
MINIMUM_BACKOFF_SECONDS = 1
MAXIMUM_BACKOFF_SECONDS = 60


class VirtualBook:
    """The synthetic limit order book: one queue estimate per held order, moved on by every quote for its instrument.

    The order engine holds a `virtual_limit` order instead of sending it, and needs to know two things about it that only the tick-by-tick quote stream can tell: how much a resting order at the same price would have filled by now, and whether it would have filled at all. That is `VirtualQueue`'s arithmetic. This class keeps one per held order, feeds each the quotes for its instrument, and writes them to `unified:orders:virtual_queue`, keyed by parent id, for the engine to read.

    It runs as its own process rather than inside the engine because the stream carries every instrument's quotes, about 112,400 of them, and decoding all of them on the engine's thread would slow every order the engine handles.

    It reads the stream with a plain `XREAD` from the moment it starts, not as a consumer group. Old quotes are of no use to an estimate, and a consumer group would keep a backlog of every entry this process did not acknowledge. Instead every estimate read back from Redis takes its next quote as a new baseline, so the trading it missed while nothing was running is not counted as trading at its price.

    Which orders are held is read from the engine's parent cache every two seconds: an open `virtual_limit` parent whose trigger has not fired. An estimate stops moving once its order fires, and is removed from Redis once its parent is no longer open.

    Attributes:
        cache (redis.Redis): The Redis client.
        parent_store (ParentStore): The engine's parent cache, read only.
        logger (logging.Logger): The logger.
        estimates (dict): Each held order's `VirtualQueue`, by parent id.
        by_instrument (dict): The parent ids held on each instrument, by instrument id.
        last_entry_id (str): The stream id read up to.
        refreshed_at (float | None): When the held orders were last read, on the monotonic clock.
        changed (set): The parent ids whose estimates have changed since they were last written.
        quotes_read (int): How many stream entries have been read.
        quotes_used (int): How many of them moved an estimate.
    """

    def __init__(self, cache, parent_store, logger):
        """Builds the book with nothing held yet.

        Args:
            cache (redis.Redis): The Redis client.
            parent_store (ParentStore): The engine's parent cache.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.parent_store = parent_store
        self.logger = logger
        self.estimates = {}
        self.by_instrument = {}
        self.last_entry_id = '$'
        self.refreshed_at = None
        self.changed = set()
        self.quotes_read = 0
        self.quotes_used = 0

    def is_held(self, document):
        """Whether a parent is a virtual limit order that is still being held rather than sent.

        Args:
            document (dict): The parent's Redis record.

        Returns:
            bool: True when its queue should be followed.
        """
        if document.get('synthetic_type') != VIRTUAL_LIMIT_TYPE:
            return False
        parameters = document.get('parameters') or {}
        if parameters.get('triggered_at') is not None:
            return False
        for leg in document.get('legs') or []:
            if leg.get('role') != 'backstop':
                return False
        return True

    def new_estimate(self, document):
        """A fresh estimate for a held parent, or None when its order cannot be read.

        Args:
            document (dict): The parent's Redis record.

        Returns:
            VirtualQueue | None: The estimate.
        """
        body = document.get('body') or {}
        parameters = document.get('parameters') or {}
        try:
            return VirtualQueue(
                document['parent_order_id'],
                document['instrument_id'],
                body.get('transaction_type'),
                parameters.get('limit_price'),
                int(body.get('quantity')),
            )
        except (KeyError, TypeError, ValueError) as error:
            self.logger.warning(
                f'Parent {document.get("parent_order_id")} is a virtual '
                f'limit order whose queue cannot be followed: {error}'
            )
            return None

    def stored_estimate(self, parent_order_id):
        """The estimate Redis already holds for a parent, or None.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            VirtualQueue | None: The estimate, rebased on its next quote.
        """
        stored = self.cache.hget(ESTIMATES_KEY, parent_order_id)
        if not stored:
            return None
        try:
            return VirtualQueue.from_document(json.loads(stored))
        except ValueError as error:
            self.logger.warning(
                f'The stored queue estimate for {parent_order_id} could not '
                f'be read, so it starts again: {error}'
            )
            return None

    def refresh(self):
        """Reads which orders are held, starting estimates for new ones and dropping those that have finished.

        An order that has fired keeps its last estimate in Redis, unchanged, for the engine to read, until its parent is no longer open.

        Returns:
            None: This method returns nothing.
        """
        self.refreshed_at = time.monotonic()
        open_ids = self.parent_store.open_parent_ids()
        held = {}
        for parent_order_id in open_ids:
            document = self.parent_store.parent(parent_order_id)
            if document is None or not self.is_held(document):
                continue
            estimate = self.estimates.get(parent_order_id)
            if estimate is None:
                estimate = self.stored_estimate(parent_order_id)
            if estimate is None:
                estimate = self.new_estimate(document)
                if estimate is not None:
                    self.changed.add(parent_order_id)
            if estimate is not None:
                held[parent_order_id] = estimate
        self.estimates = held
        self.by_instrument = {}
        for parent_order_id, estimate in held.items():
            ids = self.by_instrument.setdefault(estimate.instrument_id, [])
            ids.append(parent_order_id)
        self.drop_finished(open_ids)

    def drop_finished(self, open_ids):
        """Removes the stored estimates of parents that are no longer open.

        Args:
            open_ids (list): The ids of every open parent.

        Returns:
            None: This method returns nothing.
        """
        stored_ids = self.cache.hkeys(ESTIMATES_KEY) or []
        still_open = set(open_ids)
        finished = []
        for parent_order_id in stored_ids:
            if parent_order_id not in still_open:
                finished.append(parent_order_id)
        if finished:
            self.cache.hdel(ESTIMATES_KEY, *finished)

    def is_refresh_due(self):
        """Whether the held orders should be read again.

        Returns:
            bool: True when they have not been read for `REFRESH_SECONDS`.
        """
        if self.refreshed_at is None:
            return True
        return time.monotonic() - self.refreshed_at >= REFRESH_SECONDS

    def read_quotes(self):
        """Reads the next quotes off the stream and moves every estimate on its instrument.

        Returns:
            int: How many entries were read.
        """
        response = self.cache.xread(
            {
                QUOTES_STREAM_KEY: self.last_entry_id,
            },
            count=READ_COUNT,
            block=BLOCK_MILLISECONDS,
        )
        read = 0
        for _, entries in response or []:
            for entry_id, fields in entries:
                self.last_entry_id = entry_id
                read = read + 1
                self.apply_entry(fields)
        self.quotes_read = self.quotes_read + read
        return read

    def apply_entry(self, fields):
        """Moves every estimate on one stream entry's instrument.

        Args:
            fields (dict): The entry's fields, with the quote as JSON in `quote`.

        Returns:
            None: This method returns nothing.
        """
        if not self.by_instrument:
            return
        text = fields.get('quote')
        if not text:
            return
        try:
            quote = json.loads(text)
        except ValueError:
            return
        if not isinstance(quote, dict):
            return
        parent_ids = self.by_instrument.get(quote.get('instrument_id'))
        if not parent_ids:
            return
        self.quotes_used = self.quotes_used + 1
        for parent_order_id in parent_ids:
            if self.estimates[parent_order_id].update(quote):
                self.changed.add(parent_order_id)

    def write_changed(self):
        """Writes every estimate that changed since the last write, in one round trip.

        Returns:
            int: How many were written.
        """
        if not self.changed:
            return 0
        pipeline = self.cache.pipeline(transaction=False)
        written = 0
        for parent_order_id in sorted(self.changed):
            estimate = self.estimates.get(parent_order_id)
            if estimate is None:
                continue
            pipeline.hset(
                ESTIMATES_KEY,
                parent_order_id,
                json.dumps(estimate.document()),
            )
            written = written + 1
        pipeline.execute()
        self.changed = set()
        return written

    def run_once(self):
        """One pass: refresh the held orders if due, read quotes, and write what changed.

        Returns:
            int: How many stream entries were read.
        """
        if self.is_refresh_due():
            self.refresh()
        read = self.read_quotes()
        self.write_changed()
        return read

    def rebase_everything(self):
        """Makes every estimate take its next quote as a baseline, after a gap in reading.

        Returns:
            None: This method returns nothing.
        """
        for estimate in self.estimates.values():
            estimate.needs_baseline = True

    def run(self, stop):
        """Runs passes until stopped, waiting and retrying while Redis cannot be reached.

        A gap in reading means quotes were missed, so every estimate is rebased once Redis is back, and the stream is read from that moment.

        Args:
            stop (threading.Event): Set to stop after the pass in hand.

        Returns:
            int: 0, the exit code for a clean stop.
        """
        backoff = MINIMUM_BACKOFF_SECONDS
        while not stop.is_set():
            try:
                self.run_once()
                backoff = MINIMUM_BACKOFF_SECONDS
            except redis.RedisError as error:
                self.logger.error(
                    f'Redis could not be used ({error}); trying again in '
                    f'{backoff} seconds.'
                )
                stop.wait(backoff)
                backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)
                self.last_entry_id = '$'
                self.rebase_everything()
        self.logger.info(
            f'Stopped after reading {self.quotes_read} quotes, '
            f'{self.quotes_used} of them for a held order.'
        )
        return 0
