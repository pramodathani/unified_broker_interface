"""Rebuilding what the engine was doing, from the record rather than from Redis."""

import datetime
import json

from unified_broker_interface.utilities.order_engine.utilities.orphan_matcher import (
    OrphanMatcher,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

# How far back the carried types are read. Long enough for a stop armed before a long weekend and a
# holiday to still be found, short enough that the query stays small.
CARRY_DAYS = 30
LEG_STATES_FROM_STATUS = {
    'PENDING': 'acknowledged',
    'OPEN': 'acknowledged',
    'COMPLETE': 'filled',
    'CANCELLED': 'cancelled',
    'REJECTED': 'rejected',
    'EXPIRED': 'cancelled',
}


class EngineRecovery:
    """Rebuilds every parent the engine had not finished, before it places anything new.

    The rebuild replays the day's recorded transitions through `ParentOrder.apply_event`, which is the same method the live path uses. That is deliberate: the path recovery depends on is exercised by every order all day, so it cannot quietly stop working while nobody is restarting anything.

    Redis is not read for state. It is a cache, and the point of recovery is to be correct when the cache is gone, so the rebuild goes to `unified.synthetic_order_events` and then overwrites the cache with what it found.

    Attributes:
        cache (redis.Redis): The Redis client.
        event_log (SyntheticOrderEventLog): The record.
        parent_store (ParentStore): The Redis copy, rebuilt at the end.
        broker_names (list): Every broker's name.
        logger (logging.Logger): The logger.
        matcher (OrphanMatcher): What decides a leg left in `sending`.
    """

    def __init__(self, cache, event_log, parent_store, broker_names, logger):
        """Builds the recovery.

        Args:
            cache (redis.Redis): The Redis client.
            event_log (SyntheticOrderEventLog): The record.
            parent_store (ParentStore): The Redis copy.
            broker_names (list): Every broker's name.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.event_log = event_log
        self.parent_store = parent_store
        self.broker_names = broker_names
        self.logger = logger
        self.matcher = OrphanMatcher(logger)

    def recover(self):
        """Rebuilds every parent, brings its legs up to date and resolves what a crash left behind.

        Returns:
            dict: What was found: `parents`, `open`, `attributed`, `abandoned` and `reconciled` counts, and the rebuilt open parents.
        """
        parents = self.replay()
        open_parents = []
        for parent in parents:
            if not parent.is_terminal():
                open_parents.append(parent)

        counts = {
            'parents': len(parents),
            'open': len(open_parents),
            'attributed': 0,
            'abandoned': 0,
            'reconciled': 0,
        }
        if open_parents:
            books, polled_at = self.read_broker_books()
            claimed = self.claimed_order_ids(parents)
            for parent in open_parents:
                self.reconcile(parent, books, polled_at, claimed, counts)

        self.parent_store.rebuild(parents)
        self.logger.info(
            f'Recovered {counts["parents"]} parents, {counts["open"]} of them '
            f'open: {counts["reconciled"]} legs brought up to date, '
            f'{counts["attributed"]} orphans attributed, '
            f'{counts["abandoned"]} abandoned.'
        )
        return counts

    def window_start(self):
        """The moment the recovery scan reads from, which is the last 06:00 IST.

        Returns:
            datetime.datetime: The start of the window, in UTC.
        """
        latest_reset, _ = self.parent_store.reset_epochs()
        return datetime.datetime.fromtimestamp(
            latest_reset,
            datetime.timezone.utc,
        )

    def carried_types(self):
        """The order types whose parents outlive a trading day.

        Returns:
            list: The type names, sorted so the query is the same every time.
        """
        carried = []
        for name, synthetic_order_class in SYNTHETIC_ORDER_CLASSES.items():
            if getattr(synthetic_order_class, 'CARRIES_OVERNIGHT', False):
                carried.append(name)
        return sorted(carried)

    def carry_window_start(self):
        """How far back the carried types are read from.

        Returns:
            datetime.datetime: The start of the window, in UTC.
        """
        return self.window_start() - datetime.timedelta(days=CARRY_DAYS)

    def replay(self):
        """Rebuilds every parent from the day's recorded transitions, and the carried ones from further back.

        The two reads are merged by parent rather than concatenated. A carried parent that also did something today appears in both, and its events have to end up in one list in sequence order or `ParentOrder.from_events` replays them out of order and rebuilds the wrong state.

        Returns:
            list: The `ParentOrder` objects, in the order the record holds them.
        """
        events = self.event_log.read_since(self.window_start())
        carried = self.event_log.read_since_for_types(
            self.carry_window_start(),
            self.carried_types(),
        )
        if carried:
            events = self.merged(events, carried)
        by_parent = {}
        order = []
        for event in events:
            parent_order_id = str(event.get('parent_order_id'))
            if parent_order_id not in by_parent:
                by_parent[parent_order_id] = []
                order.append(parent_order_id)
            by_parent[parent_order_id].append(event)
        parents = []
        for parent_order_id in order:
            parent = ParentOrder.from_events(by_parent[parent_order_id])
            if parent is not None:
                parents.append(parent)
        return parents

    def merged(self, events, carried):
        """The two reads as one list, with each parent's events in sequence order and nothing counted twice.

        Args:
            events (list): The day's events.
            carried (list): The carried types' events, which may overlap.

        Returns:
            list: The merged events.
        """
        seen = set()
        merged = []
        for event in list(carried) + list(events):
            key = (str(event.get('parent_order_id')), event.get('sequence'))
            if key in seen:
                continue
            seen.add(key)
            merged.append(event)
        merged.sort(
            key=lambda event: (
                str(event.get('parent_order_id')),
                event.get('sequence') or 0,
            ),
        )
        return merged

    def read_broker_books(self):
        """Every broker's order book and when it was last read, in one round trip.

        Returns:
            tuple: The books by broker name, and when each was last polled, by broker name.
        """
        pipeline = self.cache.pipeline(transaction=False)
        for broker_name in self.broker_names:
            pipeline.hgetall(f'{broker_name}:orders:orders')
            pipeline.get(f'{broker_name}:orders:orders:polled_at')
        replies = pipeline.execute()

        books = {}
        polled_at = {}
        for position, broker_name in enumerate(self.broker_names):
            entries = replies[position * 2] or {}
            decoded = {}
            for broker_order_id, text in entries.items():
                try:
                    entry = json.loads(text)
                except (TypeError, ValueError):
                    continue
                if isinstance(entry, dict):
                    decoded[broker_order_id] = entry
            books[broker_name] = decoded
            polled_at[broker_name] = self.epoch(replies[position * 2 + 1])
        return books, polled_at

    def epoch(self, value):
        """A stored epoch as a float, or None.

        Args:
            value (str | None): The stored value.

        Returns:
            float | None: The epoch.
        """
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def claimed_order_ids(self, parents):
        """Every broker order id already belonging to a leg, which is never an orphan candidate.

        Args:
            parents (list): Every rebuilt parent.

        Returns:
            set: The `broker:order_id` pairs, as a set of `(broker, order_id)`.
        """
        claimed = set()
        for parent in parents:
            for leg in parent.legs:
                if leg.broker and leg.broker_order_id:
                    claimed.add((leg.broker, str(leg.broker_order_id)))
        return claimed

    def reconcile(self, parent, books, polled_at, claimed, counts):
        """Brings one open parent's legs up to date and resolves anything left in `sending`.

        Args:
            parent (ParentOrder): The parent.
            books (dict): Every broker's order book.
            polled_at (dict): When each broker's book was last read.
            claimed (set): The `(broker, order_id)` pairs already belonging to a leg.
            counts (dict): The running totals, changed in place.

        Returns:
            None: This method returns nothing.
        """
        for leg in parent.legs:
            if leg.state == 'sending':
                self.resolve_orphan(parent, leg, books, polled_at, claimed, counts)
                continue
            if leg.broker_order_id and not leg.is_finished():
                self.refresh_leg(parent, leg, books, counts)

    def refresh_leg(self, parent, leg, books, counts):
        """Updates one leg from the broker's own book, which moved on while the engine was down.

        A leg the book does not hold is put into `unknown` rather than assumed finished, because absence is not evidence that an order was never placed.

        Args:
            parent (ParentOrder): The parent the leg belongs to.
            leg (OrderLeg): The leg.
            books (dict): Every broker's order book.
            counts (dict): The running totals, changed in place.

        Returns:
            None: This method returns nothing.
        """
        entry = books.get(leg.broker, {}).get(str(leg.broker_order_id))
        order = (entry or {}).get('order')
        if not isinstance(order, dict):
            # Absence is not evidence the order was never placed. The book may have been trimmed,
            # or the broker may simply not report it, so the parent is parked rather than closed.
            leg.state = 'unknown'
            parent.state = 'failed'
            parent.last_error = (
                f'leg {leg.leg_id} is not in {leg.broker}\'s order book, so '
                'its outcome is unknown'
            )
            counts['reconciled'] = counts['reconciled'] + 1
            return
        status = str(order.get('status') or '').upper()
        leg.state = LEG_STATES_FROM_STATUS.get(status, leg.state)
        if order.get('filled_quantity') is not None:
            leg.filled_quantity = order['filled_quantity']
        if order.get('average_price') is not None:
            leg.average_price = order['average_price']
        if order.get('exchange_order_id'):
            leg.exchange_order_id = order['exchange_order_id']
        counts['reconciled'] = counts['reconciled'] + 1

    def resolve_orphan(self, parent, leg, books, polled_at, claimed, counts):
        """Decides what a leg left in `sending` by a crash should become, and records it.

        Args:
            parent (ParentOrder): The parent the leg belongs to.
            leg (OrderLeg): The leg.
            books (dict): Every broker's order book.
            polled_at (dict): When each broker's book was last read.
            claimed (set): The `(broker, order_id)` pairs already belonging to a leg.
            counts (dict): The running totals, changed in place.

        Returns:
            None: This method returns nothing.
        """
        book = books.get(leg.broker, {})
        claimed_here = set()
        for broker_name, broker_order_id in claimed:
            if broker_name == leg.broker:
                claimed_here.add(broker_order_id)
        decision = self.matcher.attribute(
            leg,
            book,
            polled_at.get(leg.broker),
            claimed_here,
        )
        sequence = parent.next_sequence()
        if decision['outcome'] == 'attributed':
            counts['attributed'] = counts['attributed'] + 1
            leg.broker_order_id = decision['broker_order_id']
            leg.state = 'acknowledged'
            claimed.add((leg.broker, str(decision['broker_order_id'])))
            event = 'orphan_attributed'
            parent_state = parent.state
        else:
            counts['abandoned'] = counts['abandoned'] + 1
            leg.state = 'unknown'
            event = 'orphan_abandoned'
            parent_state = 'failed'
            parent.state = 'failed'
            parent.last_error = decision['status_message']
        parent.sequence = sequence
        self.record(parent, leg, event, parent_state, decision)

    def record(self, parent, leg, event, parent_state, decision):
        """Writes what was decided about an orphaned leg, so the next start does not decide it again.

        A failure to write is logged rather than raised. Recovery has already changed what the engine believes, and refusing to start because the record could not be updated would leave the position no better off.

        Args:
            parent (ParentOrder): The parent.
            leg (OrderLeg): The leg.
            event (str): `orphan_attributed` or `orphan_abandoned`.
            parent_state (str): The parent's state after the decision.
            decision (dict): What the matcher decided.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.event_log.record({
                'parent_order_id': parent.parent_order_id,
                'sequence': parent.sequence,
                'time': datetime.datetime.now(datetime.timezone.utc),
                'event': event,
                'synthetic_type': parent.synthetic_type,
                'parent_state': parent_state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'leg_state': leg.state,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'status_message': decision['status_message'],
                'detail': {
                    'candidates': decision['candidates'],
                },
            })
        except Exception:
            self.logger.exception(
                f'The decision about orphaned leg {leg.leg_id} could not be '
                'recorded, so the next start will decide it again.'
            )
