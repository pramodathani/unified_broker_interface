"""Takes, refreshes and releases the order engine's lock over one engine's life.

The order engine takes `unified:orders:engine:lock` before it does anything else, refreshes it every ten seconds while it runs so the thirty-second expiry never lapses, and releases it on the way out so a replacement engine can start at once. Taking the lock again while already holding it succeeds and puts the expiry back to full, so an engine that runs its start-up step twice does not lock itself out.

A small stand-in replaces the Redis client. It keeps plain string keys and their expiry in seconds, and implements only `set` with `nx` and `ex`, `get`, `expire` and `delete`, which is all the lock uses. It does not count time down, so the expiry it prints is simply what the lock last set.

The lock writes the engine's process id into the key, which differs on every run, so the program prints whether the key names this lock's holder rather than the number itself.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_lock/EngineLock/example_1_one_engine_start_to_stop.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    EngineLock,
)


class ExpiringRedis:
    """A stand-in for the Redis client holding string keys and their expiry.

    Attributes:
        values (dict): The stored strings, by key.
        expiries (dict): The seconds each key was last given to live, by key.
    """

    def __init__(self):
        """Builds the stand-in with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}
        self.expiries = {}

    def set(self, key, value, nx=False, ex=None):
        """Stores a value, refusing when `nx` is set and the key exists.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Whether to store only when the key is missing.
            ex (int | None): The seconds to live, or None for no expiry.

        Returns:
            bool | None: True when stored, None when `nx` stopped it.
        """
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expiries[key] = ex
        return True

    def get(self, key):
        """Reads a value.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when missing.
        """
        return self.values.get(key)

    def expire(self, key, seconds):
        """Sets a key's time to live.

        Args:
            key (str): The key.
            seconds (int): The seconds to live.

        Returns:
            bool: True when the key exists.
        """
        if key not in self.values:
            return False
        self.expiries[key] = seconds
        return True

    def delete(self, key):
        """Removes a key.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if key not in self.values:
            return 0
        del self.values[key]
        del self.expiries[key]
        return 1


class OneEngineStartToStopExample:
    """Takes the lock, refreshes it twice, takes it again and releases it.

    Attributes:
        cache (ExpiringRedis): The stand-in Redis client.
        lock (EngineLock): The lock being shown.
    """

    def __init__(self):
        """Builds the lock over the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.cache = ExpiringRedis()
        self.lock = EngineLock(self.cache, logging.getLogger('example'))

    def describe(self):
        """Prints who holds the key and its expiry.

        Returns:
            None: This method returns nothing.
        """
        if LOCK_KEY not in self.cache.values:
            print('  Key absent')
            return
        is_ours = self.cache.values[LOCK_KEY] == self.lock.holder
        print(f'  Key held by this engine: {is_ours}, expiry {self.cache.expiries[LOCK_KEY]}s')

    def run(self):
        """Prints the lock's answers and the key's state at each step.

        Returns:
            None: This method returns nothing.
        """
        print(f'Take: {self.lock.take()}')
        self.describe()
        self.cache.expiries[LOCK_KEY] = 12
        print('Twenty seconds pass, 12s left on the key')
        print(f'Refresh: {self.lock.refresh()}')
        self.describe()
        print(f'Take again while already holding it: {self.lock.take()}')
        self.describe()
        self.lock.release()
        print('Released')
        self.describe()


if __name__ == '__main__':
    OneEngineStartToStopExample().run()
