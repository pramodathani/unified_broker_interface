"""Walks through recovery one step at a time, for a leg missing from its broker's book and a crashed leg whose book is too old to trust.

`recover` runs these steps in one call. This program runs them by hand so each result can be printed: `replay` rebuilds the parents from the record, `read_broker_books` reads every broker's polled order book with the time it was polled, `epoch` turns that stored time into a number, and `claimed_order_ids` lists the broker orders already owned by a leg, which are never matched to anything else.

Two parents were open when the engine stopped. The first had a Zerodha order acknowledged as `26091500000031`, but Zerodha's book no longer holds it, so `check_leg_in_book` parks the leg in `unknown` and fails the parent rather than assuming the order finished. The second was left in `sending` at Flattrade, and Flattrade's book was last polled five minutes ago, which is too old to match against, so `reconcile` abandons the leg and records why.

The event log is a stand-in class that keeps rows in a list, and Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`, seeded with the two brokers' books as their pollers would write them. No broker is contacted.

Notice that absence from the book and a stale book both end in `unknown` and a failed parent, but only the orphan adds a row to the record, because only its outcome was decided by guessing.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_recovery/EngineRecovery/example_2_checking_open_legs_step_by_step.py
"""

import json
import logging
import time

from test_runs import redis_stand_ins
from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
MISSING_PARENT_ID = '11111111-0000-4000-8000-000000000001'
ORPHAN_PARENT_ID = '22222222-0000-4000-8000-000000000002'
BROKER_NAMES = [
    'flattrade',
    'zerodha',
]


class ListEventLog:
    """A stand-in for the event log table that keeps every row in a list.

    Attributes:
        events (list): Every row, in the order it was written.
    """

    def __init__(self, events):
        """Builds the log holding the rows already recorded.

        Args:
            events (list): The rows the stopped engine left behind.

        Returns:
            None: This method returns nothing.
        """
        self.events = list(events)

    def read_since(self, moment):
        """Every row, ordered by parent and then sequence, as the table query orders them.

        Args:
            moment (datetime.datetime): Where the window starts, ignored because the stand-in holds one morning's rows.

        Returns:
            list: The rows.
        """
        del moment
        ordered = list(self.events)
        ordered.sort(key=self.row_order)
        return ordered

    def read_since_for_types(self, moment, types):
        """Every row whose order type is one of `types`.

        Args:
            moment (datetime.datetime): Where the window starts, ignored by the stand-in.
            types (list): The order type names to keep.

        Returns:
            list: The matching rows.
        """
        matching = []
        for event in self.read_since(moment):
            if event.get('synthetic_type') in types:
                matching.append(event)
        return matching

    def record(self, event):
        """Keeps one new row.

        Args:
            event (dict): The row.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(dict(event))

    def row_order(self, event):
        """The sort key the table query uses.

        Args:
            event (dict): One row.

        Returns:
            tuple: The parent id and the sequence number.
        """
        return (
            str(event.get('parent_order_id')),
            event.get('sequence') or 0,
        )


class CheckingOpenLegsStepByStepExample:
    """Runs recovery's steps by hand over two open parents and prints each result.

    Attributes:
        cache (redis_stand_ins.FakeEngineStoreRedis): The stand-in Redis holding both brokers' books.
        event_log (ListEventLog): The stand-in record.
        recovery (EngineRecovery): The recovery being shown.
    """

    def __init__(self):
        """Seeds the record with two open parents and Redis with the brokers' books.

        Returns:
            None: This method returns nothing.
        """
        self.cache = redis_stand_ins.FakeEngineStoreRedis()
        self.cache.hashes['zerodha:orders:orders'] = {
            '26091500000099': json.dumps({
                'order': {
                    'order_id': '26091500000099',
                    'status': 'COMPLETE',
                },
            }),
        }
        self.cache.strings['zerodha:orders:orders:polled_at'] = '1790000000.5'
        self.cache.hashes['flattrade:orders:orders'] = {}
        self.cache.strings['flattrade:orders:orders:polled_at'] = str(
            time.time() - 300.0,
        )
        self.event_log = ListEventLog(self.recorded_events())
        self.recovery = EngineRecovery(
            self.cache,
            self.event_log,
            ParentStore(self.cache),
            BROKER_NAMES,
            logging.getLogger('example'),
        )

    def recorded_events(self):
        """The rows for one acknowledged Zerodha leg and one Flattrade leg left in `sending`.

        Returns:
            list: The rows, oldest first.
        """
        return [
            {
                'time': '2026-09-23T09:30:00+00:00',
                'parent_order_id': MISSING_PARENT_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': INSTRUMENT_ID,
            },
            {
                'time': '2026-09-23T09:30:01+00:00',
                'parent_order_id': MISSING_PARENT_ID,
                'sequence': 2,
                'event': 'leg_requested',
                'leg_id': f'{MISSING_PARENT_ID}:1',
                'leg_role': 'entry',
                'leg_state': 'sending',
                'broker': 'zerodha',
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'MARKET',
                'validity': 'DAY',
                'quantity': 5,
            },
            {
                'time': '2026-09-23T09:30:01+00:00',
                'parent_order_id': MISSING_PARENT_ID,
                'sequence': 3,
                'event': 'leg_answered',
                'parent_state': 'received',
                'leg_id': f'{MISSING_PARENT_ID}:1',
                'leg_role': 'entry',
                'leg_state': 'acknowledged',
                'broker': 'zerodha',
                'broker_order_id': '26091500000031',
                'outcome': 'accepted',
            },
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': ORPHAN_PARENT_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': INSTRUMENT_ID,
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': ORPHAN_PARENT_ID,
                'sequence': 2,
                'event': 'leg_requested',
                'leg_id': f'{ORPHAN_PARENT_ID}:1',
                'leg_role': 'entry',
                'leg_state': 'sending',
                'broker': 'flattrade',
                'identifier_sent': 'RELIANCE-EQ',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'price': 1000,
            },
        ]

    def run(self):
        """Replays the record, reads the books, and checks each open parent's leg.

        Returns:
            None: This method returns nothing.
        """
        parents = self.recovery.replay()
        for parent in parents:
            leg = parent.legs[0]
            print(f'Replayed {parent.parent_order_id}: parent {parent.state}, leg at {leg.broker} {leg.state}')

        books, polled_at = self.recovery.read_broker_books()
        print(f'Orders in each book: zerodha {sorted(books["zerodha"])}, flattrade {sorted(books["flattrade"])}')
        print(f'Zerodha polled at: {polled_at["zerodha"]}')
        print(f'Stored time as a number: {self.recovery.epoch("1790000000.5")}')
        print(f'Unreadable stored time: {self.recovery.epoch("yesterday")}')

        claimed = self.recovery.claimed_order_ids(parents)
        print(f'Claimed orders: {sorted(claimed)}')

        counts = {
            'parents': len(parents),
            'open': len(parents),
            'attributed': 0,
            'abandoned': 0,
            'missing': 0,
        }
        missing_parent = parents[0]
        self.recovery.check_leg_in_book(
            missing_parent,
            missing_parent.legs[0],
            books,
            counts,
        )
        print(f'Missing leg: {missing_parent.legs[0].state}, parent {missing_parent.state}')
        print(f'Why: {missing_parent.last_error}')

        orphan_parent = parents[1]
        self.recovery.reconcile(orphan_parent, books, polled_at, claimed, counts)
        print(f'Orphan leg: {orphan_parent.legs[0].state}, parent {orphan_parent.state}')
        print(f'Why: {orphan_parent.last_error}')

        print(f'Counts: {counts}')
        added = self.event_log.events[5:]
        for event in added:
            print(f'Recorded: {event["event"]} for leg {event["leg_id"]}, parent now {event["parent_state"]}')


if __name__ == '__main__':
    CheckingOpenLegsStepByStepExample().run()
