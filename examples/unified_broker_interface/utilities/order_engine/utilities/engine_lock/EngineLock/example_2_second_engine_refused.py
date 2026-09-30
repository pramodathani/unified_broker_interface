"""Shows a second order engine refused the lock, and a running engine noticing that it has lost the lock.

Two engines reading the same intent stream could place the same order twice, so an engine that cannot take the lock stops instead of waiting. A running engine that finds another process's id in the key when it refreshes also stops, and its `release` leaves the other engine's key alone.

Two `EngineLock` objects share one small stand-in Redis client here, playing two engine processes. Each lock names its process by id in `holder`; the program sets those to the fixed labels `4101` and `4102` after building them, so the logged messages are the same on every run. A second stand-in replaces the logger and prints the error each lock logs.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_lock/EngineLock/example_2_second_engine_refused.py
"""

from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    LOCK_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    EngineLock,
)


class SharedRedis:
    """A stand-in for the Redis client both engines talk to.

    Attributes:
        values (dict): The stored strings, by key.
    """

    def __init__(self):
        """Builds the stand-in with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        """Stores a value, refusing when `nx` is set and the key exists.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Whether to store only when the key is missing.
            ex (int | None): The seconds to live, which the stand-in ignores.

        Returns:
            bool | None: True when stored, None when `nx` stopped it.
        """
        if nx and key in self.values:
            return None
        self.values[key] = value
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
        """Accepts a new time to live, which the stand-in does not track.

        Args:
            key (str): The key.
            seconds (int): The seconds to live.

        Returns:
            bool: True when the key exists.
        """
        return key in self.values

    def delete(self, key):
        """Removes a key.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if self.values.pop(key, None) is None:
            return 0
        return 1


class PrintingLogger:
    """A stand-in for a logger that prints each error."""

    def error(self, message):
        """Prints an error.

        Args:
            message (str): The error.

        Returns:
            None: This method returns nothing.
        """
        print(f'  ERROR {message}')


class SecondEngineRefusedExample:
    """Plays two engines contending for one lock.

    Attributes:
        cache (SharedRedis): The stand-in Redis client both engines share.
        first_lock (EngineLock): The first engine's lock.
        second_lock (EngineLock): The second engine's lock.
    """

    def __init__(self):
        """Builds both locks and gives them fixed holder labels.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedRedis()
        logger = PrintingLogger()
        self.first_lock = EngineLock(self.cache, logger)
        self.first_lock.holder = '4101'
        self.second_lock = EngineLock(self.cache, logger)
        self.second_lock.holder = '4102'

    def run(self):
        """Prints what each engine is told at each step.

        Returns:
            None: This method returns nothing.
        """
        print(f'First engine takes the lock: {self.first_lock.take()}')
        print('Second engine tries to take it:')
        print(f'  Answer: {self.second_lock.take()}')
        print('The first engine stalls and its key expires; the second takes it')
        del self.cache.values[LOCK_KEY]
        print(f'  Second engine takes the lock: {self.second_lock.take()}')
        print('The first engine wakes and refreshes:')
        print(f'  Answer: {self.first_lock.refresh()}')
        self.first_lock.release()
        print(f'After the first engine releases, the key names: {self.cache.get(LOCK_KEY)}')
        print(f'Second engine refreshes: {self.second_lock.refresh()}')


if __name__ == '__main__':
    SecondEngineRefusedExample().run()
