"""Calls the individual appliers that `apply_event` hands each kind of event to, for a paper order and for a crash.

`apply_event` reads the event's name and passes the event to one of six appliers. They are public, so a reader can see exactly what each kind of event changes. This program calls them directly on two parents.

The first parent is a paper order, which is never sent to a broker: `apply_received` starts it, `apply_paper_fill` records the fills, and `apply_parameters` replaces the order type's parameters, which keeps the paper fill only because the new parameters carry it. The second parent crashed while its leg was `sending`: `apply_to_leg` records the leg, and `apply_orphan` with `orphan_abandoned` marks the leg `unknown` and the parent `failed` with a message, which `apply_state_change` would also do for a plain state change.

Everything is plain data, with no store or broker involved.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_order/ParentOrder/example_3_paper_fills_and_an_abandoned_orphan.py
"""

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class PaperFillsAndAnAbandonedOrphanExample:
    """Applies events through the individual appliers and prints the result.

    Attributes:
        paper (ParentOrder): A paper order.
        crashed (ParentOrder): An order whose leg was being sent when the engine stopped.
    """

    def __init__(self):
        """Builds the two parents.

        Returns:
            None: This method returns nothing.
        """
        self.paper = ParentOrder('paper-0001', 'paper0001')
        self.crashed = ParentOrder('crash-0002')

    def run_paper(self):
        """Applies a paper order's events.

        Returns:
            None: This method returns nothing.
        """
        self.paper.apply_received({
            'synthetic_type': 'paper',
            'parent_state': 'working',
            'instrument_id': 'NFO:NIFTY25OCT25000CE',
            'detail': {
                'body': {
                    'transaction_type': 'BUY',
                    'quantity': 150,
                },
                'parameters': {
                    'fill_at': 'touch',
                },
            },
        })
        self.paper.apply_paper_fill({
            'filled_quantity': 75,
        })
        print(f'Paper after one fill: {self.paper.parameters}')
        self.paper.apply_paper_fill({})
        print(f'An event with no quantity changes nothing: {self.paper.parameters}')
        self.paper.apply_parameters({
            'detail': {
                'parameters': {
                    'fill_at': 'mid',
                    'paper_filled': 150,
                },
            },
        })
        print(f'Paper after parameters changed: {self.paper.parameters}')
        self.paper.apply_state_change({
            'parent_state': 'completed',
        })
        print(f'Paper state: {self.paper.state}, tag: {self.paper.parent_tag}')

    def run_crashed(self):
        """Applies the events of an order that was being sent when the engine stopped.

        Returns:
            None: This method returns nothing.
        """
        self.crashed.apply_received({
            'parent_state': 'working',
            'instrument_id': 'NSE:TCS',
        })
        self.crashed.apply_to_leg('leg_requested', {
            'leg_id': 'crash-0002:1',
            'leg_state': 'sending',
            'broker': 'kotak',
            'quantity': 5,
        })
        print(f'Crashed leg before recovery: {self.crashed.legs[0].state}')
        self.crashed.apply_orphan('orphan_abandoned', {
            'leg_id': 'crash-0002:1',
            'leg_state': 'unknown',
            'parent_state': 'failed',
            'status_message': 'No order in the Kotak book matched the leg',
        })
        leg = self.crashed.legs[0]
        print(f'Crashed leg after recovery: {leg.state}, parent: {self.crashed.state}')
        print(f'Last error: {self.crashed.last_error}')
        print(f'Synthetic type defaulted to: {self.crashed.synthetic_type}')

    def run(self):
        """Runs both parents.

        Returns:
            None: This method returns nothing.
        """
        self.run_paper()
        self.run_crashed()


if __name__ == '__main__':
    PaperFillsAndAnAbandonedOrphanExample().run()
