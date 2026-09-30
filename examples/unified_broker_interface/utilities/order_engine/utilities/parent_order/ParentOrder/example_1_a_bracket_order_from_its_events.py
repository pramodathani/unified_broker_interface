"""Builds a bracket order from its recorded events and asks it about its legs.

Every change to a `ParentOrder` goes through `apply_event`, with events shaped like the rows `SyntheticOrderEventLog` writes. This program applies the life of one bracket order: it is received, starts working, its entry leg is sent to Zerodha and fills in two parts, and it moves to `protecting` while a stop-loss and a target rest at the broker.

After the events are applied the program asks the parent the questions the engine asks: which leg a broker order id belongs to, which legs are live, how much of the entry has filled, which state it may move to next, and what id and sequence number the next leg and event would take. Notice that the stop and target are live while the filled entry is not, and that a `protecting` parent may be `completed` but may not go back to `working`.

The events are written out by hand, so nothing touches the database or a broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_order/ParentOrder/example_1_a_bracket_order_from_its_events.py
"""

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class BracketOrderFromItsEventsExample:
    """Applies a bracket order's events one at a time and prints what the parent reports.

    Attributes:
        parent (ParentOrder): The bracket order.
        events (list): Its events, oldest first.
    """

    def __init__(self):
        """Builds an empty parent and the events to apply.

        Returns:
            None: This method returns nothing.
        """
        parent_order_id = '3c9d2e71-0b4f-4a8e-9c61-5f0e2d7a1b88'
        self.parent = ParentOrder(parent_order_id)
        self.events = [
            {
                'event': 'parent_received',
                'sequence': 1,
                'time': '2026-09-30T09:20:00+05:30',
                'synthetic_type': 'bracket',
                'parent_state': 'received',
                'intent_id': 'a1f0c3',
                'instrument_id': 'NSE:INFY',
                'detail': {
                    'body': {
                        'transaction_type': 'BUY',
                        'order_type': 'LIMIT',
                        'price': 1520.5,
                        'quantity': 10,
                        'tag': 'swing42',
                    },
                    'parameters': {
                        'stop_loss': 1505.0,
                        'target': 1550.0,
                    },
                },
            },
            {
                'event': 'parent_state_changed',
                'sequence': 2,
                'time': '2026-09-30T09:20:00.010+05:30',
                'parent_state': 'working',
            },
            {
                'event': 'leg_requested',
                'sequence': 3,
                'time': '2026-09-30T09:20:00.020+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_role': 'entry',
                'leg_state': 'sending',
                'broker': 'zerodha',
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': 1520.5,
            },
            {
                'event': 'leg_answered',
                'sequence': 4,
                'time': '2026-09-30T09:20:00.180+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_state': 'sent',
                'broker_order_id': '250930000123456',
                'outcome': 'accepted',
            },
            {
                'event': 'leg_update',
                'sequence': 5,
                'time': '2026-09-30T09:20:03+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_state': 'partially_filled',
                'filled_quantity': 4,
            },
            {
                'event': 'leg_update',
                'sequence': 6,
                'time': '2026-09-30T09:20:05+05:30',
                'leg_id': f'{parent_order_id}:1',
                'leg_state': 'filled',
                'filled_quantity': 10,
                'average_price': 1520.35,
            },
            {
                'event': 'parent_state_changed',
                'sequence': 7,
                'time': '2026-09-30T09:20:05.010+05:30',
                'parent_state': 'protecting',
            },
            {
                'event': 'leg_answered',
                'sequence': 8,
                'time': '2026-09-30T09:20:05.200+05:30',
                'leg_id': f'{parent_order_id}:2',
                'leg_role': 'stop',
                'leg_state': 'sent',
                'broker': 'zerodha',
                'broker_order_id': '250930000123999',
                'order_type': 'SL-M',
                'trigger_price': 1505.0,
                'quantity': 10,
            },
            {
                'event': 'leg_answered',
                'sequence': 9,
                'time': '2026-09-30T09:20:05.210+05:30',
                'leg_id': f'{parent_order_id}:3',
                'leg_role': 'target',
                'leg_state': 'acknowledged',
                'broker': 'zerodha',
                'broker_order_id': '250930000124000',
                'order_type': 'LIMIT',
                'price': 1550.0,
                'quantity': 10,
            },
        ]

    def run(self):
        """Applies the events and prints the parent's answers.

        Returns:
            None: This method returns nothing.
        """
        for event in self.events:
            self.parent.apply_event(event)
            print(f'after {event["event"]:20} state={self.parent.state:10} legs={len(self.parent.legs)} filled={self.parent.filled_quantity()}')
        print(f'Tag for invented legs: {self.parent.parent_tag}')
        print(f'Caller tag: {self.parent.tag}, parameters: {self.parent.parameters}')
        stop = self.parent.leg_by_broker_order('zerodha', '250930000123999')
        print(f'Broker order 250930000123999 is leg {stop.leg_id} ({stop.role})')
        print(f'Same id at Dhan: {self.parent.leg_by_broker_order("dhan", "250930000123999")}')
        entry = self.parent.leg(f'{self.parent.parent_order_id}:1')
        print(f'Entry requested at {entry.requested_at}, answered at {entry.answered_at}')
        live_roles = []
        for leg in self.parent.live_legs():
            live_roles.append(leg.role)
        print(f'Live legs: {live_roles}')
        print(f'Legs in state sent: {len(self.parent.legs_in_state("sent"))}')
        print(f'Terminal: {self.parent.is_terminal()}')
        print(f'May become completed: {self.parent.can_change_to("completed")}')
        print(f'May go back to working: {self.parent.can_change_to("working")}')
        print(f'Next leg id: {self.parent.next_leg_id()}')
        print(f'Next sequence: {self.parent.next_sequence()}')


if __name__ == '__main__':
    BracketOrderFromItsEventsExample().run()
