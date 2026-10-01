"""Rebuilds a good-till-triggered order placed last week alongside today's orders, without counting any of its rows twice.

Recovery reads the record twice. The first read covers everything since the last 06:00 IST. The second reaches thirty days further back, but only for the order types that live overnight, which `carried_types` names. A GTT order placed on Friday that fired this morning shows up in both reads, because its newest row is from today.

`merged` joins the two reads by parent and sequence number, drops the repeated rows and puts each parent's rows back in order. `replay` does that merge itself and then rebuilds each parent, so the GTT order comes back `working` with its Friday parameters intact, next to today's plain order.

The event log is a stand-in class holding the rows each of the two reads would return, since the real one is a TimescaleDB table. Redis is only needed for the recovery window, so the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py` is enough.

A parent found only in the second read is rebuilt only when its type carries it, which `carries` asks the type: every GTT order, but only a plan marked `carries_overnight`, because it has a lifetime of days, so yesterday's ordinary plans stay gone.

Notice that the two reads return five rows between them, the merge keeps four, and the GTT parent's sequence numbers run 1, 2, 3 even though row 3 came from the first read and rows 1 and 2 from the second.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_recovery/EngineRecovery/example_3_order_kept_over_the_weekend.py
"""

import logging

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

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
GTT_PARENT_ID = 'aaaaaaaa-0000-4000-8000-000000000001'
TODAY_PARENT_ID = 'bbbbbbbb-0000-4000-8000-000000000002'


class TwoWindowEventLog:
    """A stand-in for the event log table that answers each of recovery's two reads from its own list.

    Attributes:
        today_rows (list): What a read since this morning's 06:00 IST returns.
        carried_rows (list): What the longer read for the overnight types returns.
    """

    def __init__(self, today_rows, carried_rows):
        """Builds the log.

        Args:
            today_rows (list): What a read since this morning returns.
            carried_rows (list): What the longer read returns.

        Returns:
            None: This method returns nothing.
        """
        self.today_rows = today_rows
        self.carried_rows = carried_rows

    def read_since(self, moment):
        """This morning's rows.

        Args:
            moment (datetime.datetime): Where the window starts, which the stand-in has already applied.

        Returns:
            list: The rows.
        """
        del moment
        return list(self.today_rows)

    def read_since_for_types(self, moment, types):
        """The longer window's rows whose order type is one of `types`.

        Args:
            moment (datetime.datetime): Where the window starts, which the stand-in has already applied.
            types (list): The order type names to keep.

        Returns:
            list: The matching rows.
        """
        del moment
        matching = []
        for event in self.carried_rows:
            if event.get('synthetic_type') in types:
                matching.append(event)
        return matching


class OrderKeptOverTheWeekendExample:
    """Merges the two reads of the record and rebuilds the parents from them.

    Attributes:
        event_log (TwoWindowEventLog): The stand-in record.
        recovery (EngineRecovery): The recovery being shown.
    """

    def __init__(self):
        """Builds the record with a GTT order from Friday and a plain order from today.

        Returns:
            None: This method returns nothing.
        """
        gtt_fired_today = {
            'time': '2026-09-21T03:50:00+00:00',
            'parent_order_id': GTT_PARENT_ID,
            'sequence': 3,
            'event': 'parent_state_changed',
            'synthetic_type': 'gtt',
            'parent_state': 'working',
        }
        today_rows = [
            gtt_fired_today,
            {
                'time': '2026-09-21T04:00:00+00:00',
                'parent_order_id': TODAY_PARENT_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': INSTRUMENT_ID,
            },
        ]
        carried_rows = [
            {
                'time': '2026-09-18T09:15:00+00:00',
                'parent_order_id': GTT_PARENT_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'gtt',
                'parent_state': 'received',
                'instrument_id': INSTRUMENT_ID,
                'detail': {
                    'parameters': {
                        'type': 'gtt',
                        'trigger_price': '1050',
                    },
                },
            },
            {
                'time': '2026-09-18T09:15:01+00:00',
                'parent_order_id': GTT_PARENT_ID,
                'sequence': 2,
                'event': 'parameters_changed',
                'synthetic_type': 'gtt',
                'parent_state': 'received',
                'detail': {
                    'parameters': {
                        'type': 'gtt',
                        'trigger_price': '1050',
                        'armed_on': '2026-09-18',
                    },
                },
            },
            gtt_fired_today,
        ]
        self.event_log = TwoWindowEventLog(today_rows, carried_rows)
        cache = redis_stand_ins.FakeEngineStoreRedis()
        self.recovery = EngineRecovery(
            cache,
            self.event_log,
            ParentStore(cache),
            [
                'zerodha',
            ],
            logging.getLogger('example'),
        )

    def run(self):
        """Prints the merged rows and the parents rebuilt from them.

        Returns:
            None: This method returns nothing.
        """
        carried_types = self.recovery.carried_types()
        today_rows = self.event_log.read_since(None)
        carried_rows = self.event_log.read_since_for_types(None, carried_types)
        print(f'Rows read: {len(today_rows)} since this morning, {len(carried_rows)} for {carried_types}')

        merged = self.recovery.merged(today_rows, carried_rows)
        print(f'Rows after merging: {len(merged)}')
        for event in merged:
            print(f'  {event["parent_order_id"][:8]} #{event["sequence"]} {event["event"]}')

        parents = self.recovery.replay()
        for parent in parents:
            print(f'Rebuilt {parent.parent_order_id[:8]}: {parent.synthetic_type}, {parent.state}, sequence {parent.sequence}, parameters {parent.parameters}')

        for synthetic_type, parameters in (('gtt', {}), ('plan', {'carries_overnight': True}), ('plan', {})):
            parent = ParentOrder('from-last-week')
            parent.synthetic_type = synthetic_type
            parent.parameters = parameters
            print(f'A {synthetic_type} from last week with {parameters} is carried: {self.recovery.carries(parent)}')


if __name__ == '__main__':
    OrderKeptOverTheWeekendExample().run()
