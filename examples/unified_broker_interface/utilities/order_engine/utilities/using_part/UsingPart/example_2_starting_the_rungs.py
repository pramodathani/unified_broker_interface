"""Starts a Using join of a two-step ladder, each rung a plain order, and shows each rung sent at its own price and share; then reads a TWAP Using whose second copy waits its turn.

`UsingPart.start` works out the rung prices with the ladder's own arithmetic, writes each into its copy's part record as `piece_price`, which the copy's context writes over the body, and starts each copy with its share. For a TWAP the plan reader gives every copy after the first an `elapsed` trigger for its slice's turn. A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/using_part/UsingPart/example_2_starting_the_rungs.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class StandInOrder(dict):
    """Stands in for a validated order: the body, with its quantity as a number.

    Attributes:
        quantity (int): The quantity.
    """

    def __init__(self, body):
        """Builds the order.

        Args:
            body (dict): The body.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(body)
        self.quantity = int(body['quantity'])


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records and notes every order placed.

    Attributes:
        parent (ParentOrder): The parent, a buy of ten RELIANCE.
        group_margin_legs (None): No group of legs is checked together here.
        placed (list): Every order placed, as `(role, quantity, price)`.
    """

    def __init__(self):
        """Builds the stand-in with nothing placed.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-1')
        self.parent.instrument_id = 'RELIANCE'
        self.parent.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000',
        }
        self.parent.parameters = {
            'parts': {},
        }
        self.group_margin_legs = None
        self.placed = []

    def part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record.
        """
        return copy.deepcopy(self.parent.parameters['parts'].get(path) or {})

    def set_part_record(self, path, record, message):
        """Keeps one part's record.

        Args:
            path (str): The part's path.
            record (dict): The record.
            message (str | None): Unused.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.parent.parameters['parts'][path] = record

    def read_order(self, body):
        """The body as a validated order.

        Args:
            body (dict): The body.

        Returns:
            StandInOrder: The order.
        """
        return StandInOrder(body)

    def concrete_order(self, order):
        """The order itself, since it names no references.

        Args:
            order (StandInOrder): The order.

        Returns:
            StandInOrder: The same order.
        """
        return order

    def chosen_broker(self):
        """The broker every order goes to here.

        Returns:
            str: `zerodha`.
        """
        return 'zerodha'

    def tick_size(self):
        """RELIANCE's tick size.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')

    def place_leg(self, role, order, started_at, broker_name):
        """Notes the order as placed and accepted.

        Args:
            role (str): The copy's path.
            order (StandInOrder): The order.
            started_at (float | None): Unused.
            broker_name (str): Unused.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg's id (str).
        """
        del started_at, broker_name
        self.placed.append((role, order['quantity'], order['price']))
        return {
            'outcome': 'accepted',
        }, 200, f'parent-1:{len(self.placed)}'


class StartingTheRungsExample:
    """Starts a ladder Using and reads a TWAP one."""

    def run(self):
        """Prints the orders placed and the TWAP copies' triggers.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        ladder = PlanReader('BUY').read(
            {
                'using': {
                    'order': {
                        'execution': [
                            {
                                'ladder': {
                                    'from_price': 1000,
                                    'to_price': 990,
                                    'steps': 2,
                                },
                            },
                        ],
                    },
                    'each_piece': {},
                },
            }
        )
        ladder.start(plan_order, None, None, {})
        for role, quantity, price in plan_order.placed:
            print(f'{role}: {quantity} at {price}')
        print(f"rung prices kept: {[plan_order.part_record(main.path)['piece_price'] for main in ladder.mains]}")
        twap = PlanReader('BUY').read(
            {
                'using': {
                    'order': {
                        'execution': [
                            {
                                'twap': {
                                    'slices': 2,
                                    'over_minutes': 1,
                                },
                            },
                        ],
                    },
                    'each_piece': {},
                },
            }
        )
        for main in twap.mains:
            trigger = main.trigger.described() if main.trigger is not None else 'at once'
            print(f'{main.path}: {trigger}')


if __name__ == '__main__':
    StartingTheRungsExample().run()
