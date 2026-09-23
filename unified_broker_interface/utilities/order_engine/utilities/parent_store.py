"""The Redis copy of the engine's parent orders, which is a cache and never the record."""

import datetime
import json
import zoneinfo

PARENTS_KEY = 'unified:orders:parents'
OPEN_KEY = 'unified:orders:parents:open'
CHILDREN_KEY = 'unified:orders:children'
INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
RESET_HOUR = 6


class ParentStore:
    """Keeps every parent order in Redis, so the engine and anything else can read its state without a database.

    These three keys are a cache. `unified.synthetic_order_events` is the record, and recovery rebuilds all of this from there, so a Redis that was flushed costs speed rather than correctness.

    They expire at the next 06:00 IST, moved forward by every write, exactly as `unified:order-updates` does. That is the boundary no order lives across: a parent still open at 06:00 belonged to a session that ended, and the recovery scan uses the same boundary.

    Attributes:
        cache (redis.Redis): The Redis client.
    """

    def __init__(self, cache):
        """Builds the store.

        Args:
            cache (redis.Redis): The Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache

    def reset_epochs(self, now=None):
        """The latest 06:00 IST and the next one.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            tuple: The latest reset as a float epoch, and the next as an integer epoch.
        """
        now = now or datetime.datetime.now(INDIA)
        reset = now.replace(
            hour=RESET_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        latest = reset if reset <= now else reset - datetime.timedelta(days=1)
        next_reset = latest + datetime.timedelta(days=1)
        return latest.timestamp(), int(next_reset.timestamp())

    def save(self, parent):
        """Writes one parent, its open-set membership and its legs' broker order ids, in one round trip.

        Args:
            parent (ParentOrder): The parent to write.

        Returns:
            None: This method returns nothing.
        """
        _, next_reset = self.reset_epochs()
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.hset(
            PARENTS_KEY,
            parent.parent_order_id,
            json.dumps(parent.document()),
        )
        if parent.is_terminal():
            pipeline.srem(OPEN_KEY, parent.parent_order_id)
        else:
            pipeline.sadd(OPEN_KEY, parent.parent_order_id)
        for leg in parent.legs:
            if leg.broker and leg.broker_order_id:
                pipeline.hset(
                    CHILDREN_KEY,
                    f'{leg.broker}:{leg.broker_order_id}',
                    parent.parent_order_id,
                )
        pipeline.expireat(PARENTS_KEY, next_reset)
        pipeline.expireat(OPEN_KEY, next_reset)
        pipeline.expireat(CHILDREN_KEY, next_reset)
        pipeline.execute()

    def open_parent_ids(self):
        """The ids of every parent that has not finished.

        Returns:
            list: The parent order ids.
        """
        return sorted(self.cache.smembers(OPEN_KEY) or [])

    def parent_for_broker_order(self, broker, broker_order_id):
        """Which parent a broker's order belongs to, or None.

        Args:
            broker (str): The broker's name.
            broker_order_id (str): The broker's order id.

        Returns:
            str | None: The parent order id.
        """
        return self.cache.hget(CHILDREN_KEY, f'{broker}:{broker_order_id}')

    def parent(self, parent_order_id):
        """One parent as Redis holds it, or None.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The parent's document.
        """
        stored = self.cache.hget(PARENTS_KEY, parent_order_id)
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        return document

    def rebuild(self, parents):
        """Replaces the whole cache with the parents recovery rebuilt from the event log.

        The three keys are removed first rather than written over, because a parent the event log no longer knows about — one written by an engine whose rows were deleted, say — must not survive as a ghost in the open set, where it would be recovered for ever.

        Args:
            parents (list): The `ParentOrder` objects to write.

        Returns:
            None: This method returns nothing.
        """
        _, next_reset = self.reset_epochs()
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.delete(PARENTS_KEY)
        pipeline.delete(OPEN_KEY)
        pipeline.delete(CHILDREN_KEY)
        for parent in parents:
            pipeline.hset(
                PARENTS_KEY,
                parent.parent_order_id,
                json.dumps(parent.document()),
            )
            if not parent.is_terminal():
                pipeline.sadd(OPEN_KEY, parent.parent_order_id)
            for leg in parent.legs:
                if leg.broker and leg.broker_order_id:
                    pipeline.hset(
                        CHILDREN_KEY,
                        f'{leg.broker}:{leg.broker_order_id}',
                        parent.parent_order_id,
                    )
        pipeline.expireat(PARENTS_KEY, next_reset)
        pipeline.expireat(OPEN_KEY, next_reset)
        pipeline.expireat(CHILDREN_KEY, next_reset)
        pipeline.execute()
