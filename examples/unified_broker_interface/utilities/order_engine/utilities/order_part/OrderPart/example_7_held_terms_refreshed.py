"""Rewrites the held terms of an order held on a `limit_marketable` trigger once it has become one rung of a ladder.

A `limit_marketable` trigger writes the terms the virtual book follows, the order's price and quantity, when the plan is placed. A Using join gives each of its pieces a price and share afterwards, as `piece_price` and `piece_quantity` in the piece's part record, so `OrderPart.refresh_held_terms` rewrites the terms from the order's context, which reads those. An order whose trigger wrote no terms is left as it is. A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_7_held_terms_refreshed.py
"""

import copy

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class StandInPlanOrder:
    """Stands in for the plan order: the parent with the caller's buy of nine at 1000, and its parts' records.

    Attributes:
        parent (ParentOrder): The parent.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-1')
        self.parent.instrument_id = 'RELIANCE'
        self.parent.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 9,
            'price': '1000',
        }
        self.parent.parameters = {
            'parts': {},
        }

    def part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record, empty when the part has none.
        """
        return copy.deepcopy(self.parent.parameters['parts'].get(path) or {})

    def set_part_record(self, path, record, message):
        """Keeps one part's record.

        Args:
            path (str): The part's path.
            record (dict): The record.
            message (str | None): Unused, since nothing is recorded as an event here.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.parent.parameters['parts'][path] = record


class HeldTermsRefreshedExample:
    """Refreshes a rung's held terms and leaves an order with none alone."""

    def run(self):
        """Prints the terms before and after.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = PlanReader('BUY').read({
            'order': {
                'trigger': {
                    'limit_marketable': {},
                },
            },
        })
        plan_order.set_part_record('root', {
            'piece_price': '997.50',
            'piece_quantity': 3,
            'memory': {
                'trigger': {
                    'held': {
                        'instrument_id': 'RELIANCE',
                        'transaction_type': 'BUY',
                        'price': '1000',
                        'quantity': 9,
                    },
                },
            },
        }, None)
        print('held terms before:', plan_order.part_record('root')['memory']['trigger']['held'])
        part.refresh_held_terms(plan_order)
        print('held terms after: ', plan_order.part_record('root')['memory']['trigger']['held'])
        plan_order.set_part_record('root', {
            'piece_price': '995.00',
        }, None)
        part.refresh_held_terms(plan_order)
        print('an order with no held terms:', plan_order.part_record('root'))


if __name__ == '__main__':
    HeldTermsRefreshedExample().run()
