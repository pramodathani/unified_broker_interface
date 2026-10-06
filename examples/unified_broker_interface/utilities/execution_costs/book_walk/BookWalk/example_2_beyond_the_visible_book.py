"""Lays a buy of 5,000 units against a book that shows only 3,150, and a buy against a book with gaps.

Only five levels of the book are visible, so a large order can go beyond the last one. The walk then reports the left-over quantity, which the pre-trade estimate prices with the square-root model. Levels with no price or no quantity, which a thin book often has, are left out. This program builds the books by hand, so it reads no database.

Notice that 1,850 units are left beyond 239.25, and that the gappy book keeps only its two usable levels.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/book_walk/BookWalk/example_2_beyond_the_visible_book.py
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


class BeyondTheVisibleBookExample:
    """Walks a large order and a book with gaps.

    Attributes:
        levels (list): The full book's ask levels.
    """

    def __init__(self):
        """Builds the full book's levels.

        Returns:
            None: This method returns nothing.
        """
        self.levels = []
        for price, quantity in ASKS:
            self.levels.append((decimal.Decimal(price), quantity))

    def run(self):
        """Prints both walks.

        Returns:
            None: This method returns nothing.
        """
        large = BookWalk(5000, self.levels)
        print(f'Large order: filled {large.filled_quantity()}, left over {large.remaining_quantity()}, last level {large.worst_price()}, average of the visible part {large.average_price().quantize(decimal.Decimal("0.0001"))}')
        gappy = BookWalk(100, [
            (decimal.Decimal('41.20'), 0),
            (None, 50),
            (decimal.Decimal('41.40'), 60),
            (decimal.Decimal('41.60'), 200),
        ])
        print(f'Gappy book levels kept: {gappy.levels}')
        print(f'Gappy order: average {gappy.average_price()}, levels used {gappy.levels_used()}')


if __name__ == '__main__':
    BeyondTheVisibleBookExample().run()
