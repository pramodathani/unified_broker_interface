"""Recovers an order the engine sent just before it crashed, by finding it in the broker's order book.

The engine writes a `leg_requested` row before an order leaves for the broker and a `leg_answered` row once the broker replies. This program pretends the engine stopped between the two, so the record holds a Flattrade buy of ten RELIANCE shares at 1000 whose leg is still `sending`. Flattrade's polled order book, read five seconds ago, holds exactly one order that matches what was sent, so `recover` attributes that order to the leg, records the decision, and rewrites the Redis copy of the parents.

The event log is a small stand-in class that keeps rows in a list, because the real one is a TimescaleDB table. Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`, because recovery rebuilds four Redis keys through a pipeline and that stand-in already speaks every command involved. Nothing reaches a broker: the order book is text seeded into the stand-in, exactly as the broker's poller would have written it.

Notice that the counts say one parent, one open, one orphan attributed; that the leg moves from `sending` to `acknowledged` with the broker's order id; and that one `orphan_attributed` row is added to the record, so the next start does not decide the same leg again. The recovery window always starts at the last 06:00 IST, and the order types that live overnight are read from 366 days further back.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_recovery/EngineRecovery/example_1_crashed_order_found_at_broker.py
"""

import json
import logging
import time
import zoneinfo

from test_runs import redis_stand_ins
from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

PARENT_ORDER_ID = '99999999-8888-4777-8666-555555555555'
INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
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
            events (list): The rows the crashed engine left behind.

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


class CrashedOrderFoundAtBrokerExample:
    """Runs recovery over one order left in `sending` whose match sits in the broker's book.

    Attributes:
        cache (redis_stand_ins.FakeEngineStoreRedis): The stand-in Redis holding Flattrade's order book.
        event_log (ListEventLog): The stand-in record.
        recovery (EngineRecovery): The recovery being shown.
    """

    def __init__(self):
        """Seeds the record with the crashed order and Redis with Flattrade's book.

        Returns:
            None: This method returns nothing.
        """
        self.cache = redis_stand_ins.FakeEngineStoreRedis()
        self.cache.hashes['flattrade:orders:orders'] = {
            '26091500000021': self.book_entry(),
        }
        self.cache.strings['flattrade:orders:orders:polled_at'] = str(
            time.time() - 5.0,
        )
        self.event_log = ListEventLog(self.crashed_events())
        self.recovery = EngineRecovery(
            self.cache,
            self.event_log,
            ParentStore(self.cache),
            BROKER_NAMES,
            logging.getLogger('example'),
        )

    def crashed_events(self):
        """The two rows a crash between sending an order and hearing the answer leaves behind.

        Returns:
            list: The rows, oldest first.
        """
        return [
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': PARENT_ORDER_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': INSTRUMENT_ID,
                'detail': {
                    'body': {
                        'quantity': 10,
                    },
                },
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': PARENT_ORDER_ID,
                'sequence': 2,
                'event': 'leg_requested',
                'synthetic_type': 'simple',
                'leg_id': f'{PARENT_ORDER_ID}:1',
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

    def book_entry(self):
        """One order in Flattrade's book, as the poller writes it, matching what the leg sent.

        Returns:
            str: The entry as JSON text.
        """
        return json.dumps({
            'observed_at': 1790000000.0,
            'source': 'rest',
            'order': {
                'order_id': '26091500000021',
                'status': 'OPEN',
                'tradingsymbol': 'RELIANCE-EQ',
                'instrument_token': '2885',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'quantity': 10,
                'filled_quantity': 0,
                'price': 1000,
                'trigger_price': None,
                'average_price': None,
                'tag': None,
                'order_timestamp': '2026-09-23T10:00:02+00:00',
            },
            'data': {},
        })

    def run(self):
        """Prints the recovery window, runs recovery, and prints what it decided.

        Returns:
            None: This method returns nothing.
        """
        india = zoneinfo.ZoneInfo('Asia/Kolkata')
        window_start = self.recovery.window_start()
        carry_window_start = self.recovery.carry_window_start()
        print(f'Window starts at {window_start.astimezone(india):%H:%M} IST')
        print(f'Carried types: {self.recovery.carried_types()}')
        print(f'Carried types are read from {(window_start - carry_window_start).days} days earlier')

        counts = self.recovery.recover()
        print(f'Counts: {counts}')

        stored = self.cache.hashes['unified:orders:parents'][PARENT_ORDER_ID]
        parent = ParentOrder.from_document(json.loads(stored))
        leg = parent.legs[0]
        print(f'Parent state: {parent.state}')
        print(f'Leg state: {leg.state}, broker order id: {leg.broker_order_id}')
        print(f'Open parents in Redis: {sorted(self.cache.sets["unified:orders:parents:open"])}')
        added = self.event_log.events[2]
        print(f'Recorded: {added["event"]} with candidates {added["detail"]["candidates"]}')
        print(f'Reason: {added["status_message"]}')


if __name__ == '__main__':
    CrashedOrderFoundAtBrokerExample().run()
