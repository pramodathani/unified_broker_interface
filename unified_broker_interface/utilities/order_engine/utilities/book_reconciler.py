"""Finding the order changes the engine missed, by comparing its open legs with the brokers' polled order books."""

import json
import time

from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    ORDER_UPDATES_STREAM_FIELD,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)

FINISHED_STATUSES = (
    'COMPLETE',
    'CANCELLED',
    'REJECTED',
    'EXPIRED',
)


class BookReconciler:
    """Compares every open leg with its broker's polled order book, and turns each difference into an order update.

    The engine learns what happens to its orders from `unified:order-updates:stream`, which only the brokers' order websockets feed. A broker without an order socket, or a socket that drops a message, leaves a leg that the broker has filled or cancelled looking live to the engine forever. Each broker's REST poller keeps the whole day's book in `<broker>:orders:orders` regardless, so every few seconds this class reads that book for the engine's open legs.

    Only changes that move a leg forward are taken: a finished status, or more filled than the leg records. A poll is older than a socket message about the same order, so an `OPEN` in the book next to a leg the socket already filled is the book being behind, not the order reopening. A difference found here is handed to the follower as the socket would have delivered it, so fills, reactions and parents finishing all follow the one path they already take.

    Attributes:
        cache (redis.Redis): The Redis client.
        parent_store (ParentStore): The Redis copy of the parents.
        interval_seconds (float): How long to wait between passes; 0 turns reconciliation off.
        checked_at (float): When the last pass ran, on the monotonic clock.
        passes (int): How many passes have run.
        found (int): How many missed changes the passes found.
    """

    def __init__(self, cache, parent_store, interval_seconds):
        """Builds the reconciler.

        Args:
            cache (redis.Redis): The Redis client.
            parent_store (ParentStore): The Redis copy of the parents.
            interval_seconds (float): How long to wait between passes; 0 turns reconciliation off.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.parent_store = parent_store
        self.interval_seconds = interval_seconds
        self.checked_at = time.monotonic()
        self.passes = 0
        self.found = 0

    def due(self, now=None):
        """Whether enough time has passed for another pass.

        Args:
            now (float | None): The monotonic time, or None for now.

        Returns:
            bool: True when a pass is due and reconciliation is on.
        """
        if self.interval_seconds <= 0:
            return False
        now = now if now is not None else time.monotonic()
        return (now - self.checked_at) >= self.interval_seconds

    def open_legs(self):
        """Every leg the engine has sent and not yet seen finish, with the parent it belongs to.

        Returns:
            list: One `(parent_order_id, leg)` pair per leg, where leg is an `OrderLeg`.
        """
        documents = self.parent_store.parents(
            self.parent_store.open_parent_ids(),
        )
        legs = []
        for document in documents:
            parent = ParentOrder.from_document(document)
            for leg in parent.legs:
                if not leg.broker or not leg.broker_order_id:
                    continue
                if leg.is_finished():
                    continue
                legs.append((parent.parent_order_id, leg))
        return legs

    def book_entries(self, legs):
        """Each leg's entry in its broker's order book, read in one round trip.

        Args:
            legs (list): The `(parent_order_id, leg)` pairs.

        Returns:
            list: One order (dict on the order contract) or None per leg, in the same order.
        """
        pipeline = self.cache.pipeline(transaction=False)
        for _, leg in legs:
            pipeline.hget(f'{leg.broker}:orders:orders', leg.broker_order_id)
        orders = []
        for stored in pipeline.execute():
            orders.append(self.order_in_entry(stored))
        return orders

    def order_in_entry(self, stored):
        """The normalized order inside one stored book entry.

        Args:
            stored (str | None): The book entry as Redis holds it.

        Returns:
            dict | None: The order, or None when there is no readable entry.
        """
        if not stored:
            return None
        try:
            entry = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(entry, dict):
            return None
        order = entry.get('order')
        if not isinstance(order, dict):
            return None
        return order

    def is_ahead(self, leg, order):
        """Whether the book knows something about this order that the leg does not.

        Args:
            leg (OrderLeg): The engine's leg.
            order (dict): The book's order, on the order contract.

        Returns:
            bool: True when the book shows a finished status, or more filled than the leg records.
        """
        status = str(order.get('status') or '').upper()
        if status in FINISHED_STATUSES:
            return True
        filled_quantity = order.get('filled_quantity')
        if not isinstance(filled_quantity, (int, float)):
            return False
        return filled_quantity > (leg.filled_quantity or 0)

    def missed_updates(self):
        """Runs one pass and answers the order updates the engine missed.

        Returns:
            list: One `(parent_order_id, broker, fields)` triple per missed change, where fields is shaped like an entry of `unified:order-updates:stream`.
        """
        self.checked_at = time.monotonic()
        self.passes = self.passes + 1
        legs = self.open_legs()
        if not legs:
            return []
        orders = self.book_entries(legs)
        missed = []
        for (parent_order_id, leg), order in zip(legs, orders):
            if order is None:
                continue
            if not self.is_ahead(leg, order):
                continue
            update = dict(order)
            update['broker'] = leg.broker
            update['order_id'] = leg.broker_order_id
            fields = {
                ORDER_UPDATES_STREAM_FIELD: json.dumps(update),
            }
            missed.append((parent_order_id, leg.broker, fields))
        self.found = self.found + len(missed)
        return missed
