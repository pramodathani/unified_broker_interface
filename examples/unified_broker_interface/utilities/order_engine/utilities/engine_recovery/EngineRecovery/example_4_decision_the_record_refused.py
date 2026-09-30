"""Shows that recovery still decides an orphaned leg when the record cannot be written, and logs the failure instead of refusing to start.

A leg left in `sending` by a crash is decided by `resolve_orphan`, which matches it against the broker's order book and then calls `record` to write an `orphan_attributed` or `orphan_abandoned` row, so the next start does not decide it again. If that write fails, recovery has still changed what the engine believes about the leg, and stopping would leave the position no better off, so the failure is logged and recovery carries on.

This program builds one parent whose Flattrade leg is in `sending`, with Flattrade's freshly polled book holding exactly one matching order. The first event log refuses every write, as a database that has gone away would. The leg is attributed anyway and the logger reports the lost row. The program then writes the same decision with `record` to a working log, as the next start would.

The event logs and the logger are small stand-in classes defined here, so the output shows exactly what was logged. The broker book is a plain dictionary shaped like the entries `flattrade:orders:orders` holds, and no broker is contacted.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_recovery/EngineRecovery/example_4_decision_the_record_refused.py
"""

import time

from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)

PARENT_ORDER_ID = '99999999-8888-4777-8666-555555555555'


class RefusingEventLog:
    """A stand-in for an event log whose database has gone away.

    Attributes:
        attempts (int): How many writes were tried.
    """

    def __init__(self):
        """Builds the log.

        Returns:
            None: This method returns nothing.
        """
        self.attempts = 0

    def record(self, event):
        """Refuses the write.

        Args:
            event (dict): The row.

        Returns:
            None: This method returns nothing.

        Raises:
            ConnectionError: Always.
        """
        del event
        self.attempts = self.attempts + 1
        raise ConnectionError('the database is not reachable')


class KeepingEventLog:
    """A stand-in for a working event log that keeps rows in a list.

    Attributes:
        events (list): Every row written.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def record(self, event):
        """Keeps one row.

        Args:
            event (dict): The row.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(dict(event))


class PrintingLogger:
    """A stand-in logger that prints each message with its level."""

    def info(self, message):
        """Prints an informational message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'[info] {message}')

    def exception(self, message):
        """Prints an error message logged while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'[error] {message}')


class DecisionTheRecordRefusedExample:
    """Decides one orphaned leg with a log that refuses the write, then records it with one that works.

    Attributes:
        refusing_log (RefusingEventLog): The failing record.
        recovery (EngineRecovery): The recovery being shown.
        parent (ParentOrder): The parent with the orphaned leg.
    """

    def __init__(self):
        """Builds the parent from its two recorded rows and the recovery over a failing log.

        Returns:
            None: This method returns nothing.
        """
        self.refusing_log = RefusingEventLog()
        self.recovery = EngineRecovery(
            None,
            self.refusing_log,
            None,
            [
                'flattrade',
            ],
            PrintingLogger(),
        )
        self.parent = ParentOrder.from_events([
            {
                'time': '2026-09-23T10:00:00+00:00',
                'parent_order_id': PARENT_ORDER_ID,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': 'simple',
                'parent_state': 'received',
                'instrument_id': '11111111-1111-5111-8111-000000000001',
            },
            {
                'time': '2026-09-23T10:00:01+00:00',
                'parent_order_id': PARENT_ORDER_ID,
                'sequence': 2,
                'event': 'leg_requested',
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
        ])

    def run(self):
        """Resolves the orphan, shows the logged failure, and records the decision on a working log.

        Returns:
            None: This method returns nothing.
        """
        books = {
            'flattrade': {
                '26091500000021': {
                    'order': {
                        'order_id': '26091500000021',
                        'status': 'OPEN',
                        'tradingsymbol': 'RELIANCE-EQ',
                        'transaction_type': 'BUY',
                        'product': 'MIS',
                        'order_type': 'LIMIT',
                        'validity': 'DAY',
                        'quantity': 10,
                        'price': 1000,
                        'order_timestamp': '2026-09-23T10:00:02+00:00',
                    },
                },
            },
        }
        polled_at = {
            'flattrade': time.time() - 5.0,
        }
        claimed = set()
        counts = {
            'parents': 1,
            'open': 1,
            'attributed': 0,
            'abandoned': 0,
            'missing': 0,
        }
        leg = self.parent.legs[0]
        self.recovery.resolve_orphan(
            self.parent,
            leg,
            books,
            polled_at,
            claimed,
            counts,
        )
        print(f'Writes tried: {self.refusing_log.attempts}')
        print(f'Leg: {leg.state}, broker order id {leg.broker_order_id}, parent sequence {self.parent.sequence}')
        print(f'Now claimed: {sorted(claimed)}')
        print(f'Counts: {counts}')

        keeping_log = KeepingEventLog()
        self.recovery.event_log = keeping_log
        decision = {
            'status_message': 'exactly one unclaimed order at the broker matches what was sent',
            'candidates': [
                '26091500000021',
            ],
        }
        self.recovery.record(
            self.parent,
            leg,
            'orphan_attributed',
            self.parent.state,
            decision,
        )
        row = keeping_log.events[0]
        print(f'Recorded on retry: {row["event"]} #{row["sequence"]}, leg {row["leg_state"]}, order {row["broker_order_id"]}')


if __name__ == '__main__':
    DecisionTheRecordRefusedExample().run()
