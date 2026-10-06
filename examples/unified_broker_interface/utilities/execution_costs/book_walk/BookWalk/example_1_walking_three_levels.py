"""Lays a buy of 1,200 units of a NIFTY option against the five ask levels it would trade with.

The best ask holds only 300 units, so the order takes the next two levels as well, and its average price is worse than the best ask. This program builds the book by hand, so it reads no database.

Notice that the average of 238.63125 is 0.13125 above the best ask, which is the cost of walking the book.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/book_walk/BookWalk/example_1_walking_three_levels.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.book_walk import (
    BookWalk,
)

ASKS = [
    ('238.50', 300),
    ('238.60', 450),
    ('238.75', 600),
    ('239.00', 1000),
    ('239.25', 800),
]


class WalkingThreeLevelsExample:
    """Walks one order and prints what it reaches.

    Attributes:
        walk (BookWalk): The walk.
    """

    def __init__(self):
        """Builds the walk.

        Returns:
            None: This method returns nothing.
        """
        levels = []
        for price, quantity in ASKS:
            levels.append((decimal.Decimal(price), quantity))
        self.walk = BookWalk(1200, levels)

    def run(self):
        """Prints the walk's figures.

        Returns:
            None: This method returns nothing.
        """
        print(f'Visible: {self.walk.visible_quantity()} units')
        print(f'Filled: {self.walk.filled_quantity()}, left over: {self.walk.remaining_quantity()}')
        print(f'Levels used: {self.walk.levels_used()}, worst price: {self.walk.worst_price()}')
        print(f'Average price: {self.walk.average_price()}')


if __name__ == '__main__':
    WalkingThreeLevelsExample().run()
