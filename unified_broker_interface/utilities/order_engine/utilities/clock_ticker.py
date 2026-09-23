"""Waking the order types that are waiting for a time rather than for a fill."""

import time

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

TICK_SECONDS = 1.0


class ClockTicker:
    """Gives every open parent that cares about time a chance to act, about once a second.

    Most order types do nothing until something fills. The time-based ones do the opposite: they are waiting for ten past three, or for twenty minutes to have gone by, and nothing at a broker will ever tell them so.

    The engine's own loop already wakes about once a second, because its read of the intent stream blocks for a second at a time. This turns that into a tick rather than adding a thread, so there is still one thing touching a parent at a time and nothing to lock.

    Only types that say `WANTS_CLOCK` are read at all. An engine running a hundred plain orders does no extra work, because none of them wants a tick, and the open set is read only when at least one type in the registry does.

    Attributes:
        parent_store (ParentStore): The Redis copy of the parents.
        event_log (SyntheticOrderEventLog): The record.
        placement (EnginePlacement): What a type uses to place, cancel or change a leg.
        logger (logging.Logger): The logger.
        gates (RiskGates | None): The limits.
        ticked_at (float): When the last tick ran, on the monotonic clock.
        ticks (int): How many ticks have run.
        acted (int): How many times a parent did something on a tick.
    """

    def __init__(self, parent_store, event_log, placement, logger, gates=None):
        """Builds the ticker.

        Args:
            parent_store (ParentStore): The Redis copy of the parents.
            event_log (SyntheticOrderEventLog): The record.
            placement (EnginePlacement): What a type uses to act.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits.

        Returns:
            None: This method returns nothing.
        """
        self.parent_store = parent_store
        self.event_log = event_log
        self.placement = placement
        self.logger = logger
        self.gates = gates
        self.ticked_at = time.monotonic()
        self.ticks = 0
        self.acted = 0

    def timed_types(self):
        """The names of the order types that want a tick.

        Returns:
            set: The type names.
        """
        wanted = set()
        for name, synthetic_order_class in SYNTHETIC_ORDER_CLASSES.items():
            if getattr(synthetic_order_class, 'WANTS_CLOCK', False):
                wanted.add(name)
        return wanted

    def due(self, now=None):
        """Whether enough time has passed for another tick.

        Args:
            now (float | None): The monotonic time, or None for now.

        Returns:
            bool: True when a tick is due.
        """
        now = now if now is not None else time.monotonic()
        return (now - self.ticked_at) >= TICK_SECONDS

    def tick(self):
        """Gives every open parent of a timed type a chance to act.

        A parent that raises is logged and the rest still get their tick. One order type failing must not stop a square-off somebody is relying on.

        Returns:
            int: How many parents did something.
        """
        self.ticked_at = time.monotonic()
        self.ticks = self.ticks + 1
        wanted = self.timed_types()
        if not wanted:
            return 0
        acted = 0
        for parent_order_id in self.parent_store.open_parent_ids():
            document = self.parent_store.parent(parent_order_id)
            if document is None:
                continue
            if document.get('synthetic_type') not in wanted:
                continue
            if self.run_one(document):
                acted = acted + 1
        self.acted = self.acted + acted
        return acted

    def run_one(self, document):
        """Gives one parent its tick.

        Args:
            document (dict): The parent's Redis record.

        Returns:
            bool: True when the parent did something.
        """
        parent = ParentOrder.from_document(document)
        synthetic_order_class = SYNTHETIC_ORDER_CLASSES.get(
            parent.synthetic_type,
        )
        if synthetic_order_class is None:
            return False
        runner = synthetic_order_class(
            parent,
            self.placement,
            self.event_log,
            self.parent_store,
            self.logger,
            self.gates,
        )
        try:
            return bool(runner.on_clock_tick(time.time()))
        except Exception:
            self.logger.exception(
                f'Parent {parent.parent_order_id} failed on a clock tick.'
            )
            return False
