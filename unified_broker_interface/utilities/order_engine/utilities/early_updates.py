"""Order updates that arrived before the engine knew which parent their order belongs to."""

import threading
import time

EARLY_UPDATE_SECONDS = 30.0
MAXIMUM_EARLY_UPDATES = 10000


class EarlyUpdates:
    """Holds order updates for orders the engine may not have registered yet, so a fast fill is applied late rather than lost.

    A broker can report an order filled before the engine has saved the order's id against its parent, because the fill comes over a websocket while the engine is still reading the answer to the placement. Such an update names no known parent when it arrives. It is held here, in arrival order, and handed back once the order id is known. An update still unknown after `EARLY_UPDATE_SECONDS` belongs to an order the engine never placed, and is dropped.

    Attributes:
        held (list): The held updates, oldest first, each a dict with `held_at` (float, a monotonic time), `key` (str, `broker:order_id`) and `fields` (dict, the stream entry's fields).
        hold_seconds (float): How long an update is held before it is dropped.
        maximum_held (int): The most updates held at once; the oldest are dropped beyond it.
        dropped (int): How many held updates were dropped without ever matching a parent.
        lock (threading.Lock): Guards `held` and `dropped`, since the main thread and the worker threads both hold updates.
    """

    def __init__(
        self,
        hold_seconds=EARLY_UPDATE_SECONDS,
        maximum_held=MAXIMUM_EARLY_UPDATES,
    ):
        """Builds an empty holding area.

        Args:
            hold_seconds (float): How long an update is held before it is dropped.
            maximum_held (int): The most updates held at once.

        Returns:
            None: This method returns nothing.
        """
        self.held = []
        self.hold_seconds = hold_seconds
        self.maximum_held = maximum_held
        self.dropped = 0
        self.lock = threading.Lock()

    def hold(self, key, fields):
        """Holds one update until its order is known or it is too old.

        Args:
            key (str): The order's `broker:order_id`.
            fields (dict): The stream entry's fields, exactly as they were read.

        Returns:
            None: This method returns nothing.
        """
        with self.lock:
            self.held.append({
                'held_at': time.monotonic(),
                'key': key,
                'fields': fields,
            })
            while len(self.held) > self.maximum_held:
                self.held.pop(0)
                self.dropped = self.dropped + 1

    def drop_expired(self):
        """Drops every held update older than the holding time.

        Returns:
            None: This method returns nothing.
        """
        oldest_kept = time.monotonic() - self.hold_seconds
        with self.lock:
            kept = []
            for entry in self.held:
                if entry['held_at'] >= oldest_kept:
                    kept.append(entry)
                else:
                    self.dropped = self.dropped + 1
            self.held = kept

    def keys(self):
        """The distinct order keys being held, in the order they first arrived.

        Returns:
            list: The `broker:order_id` keys.
        """
        keys = []
        seen = set()
        with self.lock:
            for entry in self.held:
                if entry['key'] not in seen:
                    seen.add(entry['key'])
                    keys.append(entry['key'])
        return keys

    def take(self, known_keys):
        """Removes and returns every held update whose order is now known, oldest first.

        Args:
            known_keys (set): The `broker:order_id` keys that now name a parent.

        Returns:
            list: The stream entries' fields (dict), in arrival order.
        """
        taken = []
        kept = []
        with self.lock:
            for entry in self.held:
                if entry['key'] in known_keys:
                    taken.append(entry['fields'])
                else:
                    kept.append(entry)
            self.held = kept
        return taken
