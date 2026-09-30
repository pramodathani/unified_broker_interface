"""Rebuilds a parent order the two ways the engine does after a restart: from Redis and from the event log.

The engine keeps each parent in Redis as the dictionary `document()` returns, and rebuilds it with `ParentOrder.from_document()`. When Redis has been flushed, it replays the day's rows from the event log with `ParentOrder.from_events()` instead. The event table has no unique constraint, so the same row can appear twice, and replay ignores a sequence number it has already applied.

The program rebuilds a simple limit order from its events, with one event deliberately duplicated, saves it as a document, rebuilds it again from that document and checks the two agree. It also shows the short tag the engine derives from a parent id, since a broker tag may hold only letters and digits, and the `text` helper that turns ids into text.

Nothing touches Redis or the database: the events and the document are plain dictionaries.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_order/ParentOrder/example_2_rebuilding_after_a_restart.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class RebuildingAfterARestartExample:
    """Rebuilds one parent from events and from its document.

    Attributes:
        events (list): The parent's rows as the event log returns them, with one row repeated.
    """

    def __init__(self):
        """Prepares the recorded events.

        Returns:
            None: This method returns nothing.
        """
        parent_order_id = '9e07aa10-4c2b-4d1e-8f3a-7b6c5d4e3f21'
        leg_answered = {
            'parent_order_id': parent_order_id,
            'event': 'leg_answered',
            'sequence': 3,
            'time': '2026-09-30T10:02:00.150+05:30',
            'leg_id': f'{parent_order_id}:1',
            'leg_state': 'sent',
            'broker_order_id': '1102509300004567',
            'outcome': 'accepted',
        }
        self.events = [
            {
                'parent_order_id': parent_order_id,
                'event': 'parent_received',
                'sequence': 1,
                'time': '2026-09-30T10:02:00+05:30',
                'synthetic_type': 'simple',
                'parent_state': 'working',
                'intent_id': 'b7e2d4',
                'instrument_id': 'NSE:SBIN',
                'detail': {
                    'body': {
                        'transaction_type': 'SELL',
                        'order_type': 'LIMIT',
                        'price': 812.4,
                        'quantity': 50,
                    },
                },
            },
            {
                'parent_order_id': parent_order_id,
                'event': 'leg_requested',
                'sequence': 2,
                'time': '2026-09-30T10:02:00.010+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_role': 'entry',
                'leg_state': 'sending',
                'broker': 'dhan',
                'quantity': 50,
                'price': 812.4,
            },
            leg_answered,
            dict(leg_answered),
            {
                'parent_order_id': parent_order_id,
                'event': 'leg_update',
                'sequence': 4,
                'time': '2026-09-30T10:04:10+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_state': 'filled',
                'filled_quantity': 50,
                'average_price': 812.4,
            },
            {
                'parent_order_id': parent_order_id,
                'event': 'parent_state_changed',
                'sequence': 5,
                'time': '2026-09-30T10:04:10.005+05:30',
                'parent_state': 'completed',
            },
        ]

    def run(self):
        """Prints the parent rebuilt from events and from its document.

        Returns:
            None: This method returns nothing.
        """
        replayed = ParentOrder.from_events(self.events)
        print(f'Events read: {len(self.events)}, last sequence applied: {replayed.sequence}')
        print(f'Replayed: state={replayed.state} legs={len(replayed.legs)} filled={replayed.filled_quantity()} terminal={replayed.is_terminal()}')
        print(f'Created at {replayed.created_at}, updated at {replayed.updated_at}')
        print(f'Tag from id: {replayed.tag_from_id(replayed.parent_order_id)}')
        print(f'Intent id as text: {replayed.text(replayed.intent_id)!r}, missing value as text: {replayed.text(None)!r}')
        saved = json.dumps(replayed.document())
        restored = ParentOrder.from_document(json.loads(saved))
        print(f'Document is {len(saved)} characters of JSON')
        print(f'Rebuilt from document matches: {restored.document() == replayed.document()}')
        print(f'Nothing to replay: {ParentOrder.from_events([])}')


if __name__ == '__main__':
    RebuildingAfterARestartExample().run()
