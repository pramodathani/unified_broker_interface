"""Bringing the engine's Redis caches back after they expire at six in the morning."""


class DayRoll:
    """Rebuilds the parent caches when the day rolls over, so a carried parent does not vanish with them.

    `unified:orders:parents`, its open set and its child index all expire at the next 06:00 IST, which is the same rule `unified:order-updates` follows and is right for almost everything: an order placed on Tuesday is finished on Tuesday, and a cache that cleans itself out is one nobody has to remember to clear.

    It is wrong for the few types that outlive a day. A stop armed on Monday for a position held until Friday is in the event log, and would be rebuilt correctly by the next restart, but the engine does not restart every morning. At six o'clock the keys simply expire underneath a running engine, the open set becomes empty, and the clock and price tickers find nothing to tick. The order is not lost, but it stops working, silently, and starts again whenever somebody next restarts the daemon.

    So the engine watches for the moment it crosses a reset, and rebuilds the caches from the record when it does. That reuses the recovery path rather than adding a second way to get parents into Redis, which matters because the recovery path is the one exercised by every restart and therefore the one that can be trusted.

    **Broker order ids are not reconciled here**, unlike at startup. A rollover happens at six in the morning, hours before any exchange opens and hours after the last one closed, so nothing has changed at a broker since the state being rebuilt was written. Reading ten order books to confirm that would be ten round trips to learn nothing.

    Attributes:
        recovery (EngineRecovery): What replays the record into parents.
        parent_store (ParentStore): The Redis copy being rebuilt.
        logger (logging.Logger): The logger.
        last_reset (float): The reset epoch this engine has already accounted for.
        rolls (int): How many times the caches have been rebuilt.
    """

    def __init__(self, recovery, parent_store, logger):
        """Builds the roll, taking the current day as already accounted for.

        Args:
            recovery (EngineRecovery): What replays the record into parents.
            parent_store (ParentStore): The Redis copy being rebuilt.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.recovery = recovery
        self.parent_store = parent_store
        self.logger = logger
        self.last_reset, _ = parent_store.reset_epochs()
        self.rolls = 0

    def due(self, now=None):
        """Whether the engine has crossed into a new trading day since it last looked.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            bool: True when the caches need rebuilding.
        """
        latest, _ = self.parent_store.reset_epochs(now)
        return latest > self.last_reset

    def roll(self, now=None):
        """Rebuilds the caches from the record, and remembers the day it did it for.

        A failure is logged and the day is **not** marked as done, so the next pass through the loop tries again. Leaving the caches empty until somebody notices would mean every carried order quietly not working, which is the failure this class exists to prevent.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            int: How many open parents came back, or -1 when the rebuild failed.
        """
        try:
            parents = self.recovery.replay()
        except Exception as exception:
            self.logger.error(
                'The day rolled over and the parent caches could not be '
                f'rebuilt, so this will be tried again: '
                f'{type(exception).__name__}: {exception}'
            )
            return -1
        self.parent_store.rebuild(parents)
        still_open = sum(
            1 for parent in parents if not parent.is_terminal()
        )
        latest, _ = self.parent_store.reset_epochs(now)
        self.last_reset = latest
        self.rolls = self.rolls + 1
        self.logger.info(
            f'The day rolled over. Rebuilt {len(parents)} parents, '
            f'{still_open} of them still open.'
        )
        return still_open
