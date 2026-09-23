"""The lock that keeps exactly one order engine running against one Redis."""

import os

LOCK_KEY = 'unified:orders:engine:lock'
LOCK_SECONDS = 30
REFRESH_SECONDS = 10


class EngineLock:
    """A short-lived Redis key naming the process allowed to place orders.

    Two engines reading the same intent stream would each hold the group's pending entries separately and could place the same order twice, with real money behind both. The lock is therefore taken before anything else and refreshed for as long as the engine runs, and an engine that cannot take it exits rather than waiting, so a second copy started by mistake fails loudly.

    The key expires by itself, so an engine killed outright does not lock the next one out for longer than `LOCK_SECONDS`.

    Attributes:
        cache (redis.Redis): The Redis client.
        logger (logging.Logger): The logger.
        holder (str): The value written into the key, naming this process.
    """

    def __init__(self, cache, logger):
        """Builds the lock for this process.

        Args:
            cache (redis.Redis): The Redis client.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.logger = logger
        self.holder = str(os.getpid())

    def take(self):
        """Takes the lock, or reports who holds it.

        Returns:
            bool: True when this process now holds the lock, and False when another does.
        """
        taken = self.cache.set(
            LOCK_KEY,
            self.holder,
            nx=True,
            ex=LOCK_SECONDS,
        )
        if taken:
            return True
        current_holder = self.cache.get(LOCK_KEY)
        if current_holder == self.holder:
            self.cache.expire(LOCK_KEY, LOCK_SECONDS)
            return True
        self.logger.error(
            f'Another order engine holds {LOCK_KEY} (pid {current_holder}). '
            'Two engines would place every order twice, so this one is stopping.'
        )
        return False

    def refresh(self):
        """Puts the expiry back to its full length, unless another process has taken the key.

        Returns:
            bool: True when this process still holds the lock, and False when it has lost it.
        """
        current_holder = self.cache.get(LOCK_KEY)
        if current_holder != self.holder:
            self.logger.error(
                f'{LOCK_KEY} is now held by pid {current_holder} rather than '
                f'{self.holder}, so this engine is stopping rather than '
                'placing orders beside another one.'
            )
            return False
        self.cache.expire(LOCK_KEY, LOCK_SECONDS)
        return True

    def release(self):
        """Gives the lock up, so a replacement engine can start at once.

        A lock held by another process is left alone, because losing the lock is one of the reasons this engine stops.

        Returns:
            None: This method returns nothing.
        """
        try:
            if self.cache.get(LOCK_KEY) == self.holder:
                self.cache.delete(LOCK_KEY)
        except Exception:
            self.logger.warning(
                f'{LOCK_KEY} could not be released; it expires by itself '
                f'within {LOCK_SECONDS} seconds.'
            )
