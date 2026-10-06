"""Estimates a buy of 1,200 units and a sell of 400 units of a NIFTY option against the book as it stands.

Both orders fit inside the five visible levels, so the estimate is exact for this book and needs no model: half the spread to reach the other side, plus the walk through the levels beyond the best one. This program builds the book by hand, so it reads no database.

Notice that the buy costs 16.00 basis points, about 457 rupees, of which 0.25 a unit is the spread and 0.13 the walk.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/pre_trade_estimate/PreTradeEstimate/example_1_an_order_the_book_covers.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.pre_trade_estimate import (
    PreTradeEstimate,
)

BIDS = [
    ('238.00', 300),
    ('237.90', 450),
    ('237.75', 600),
    ('237.50', 1000),
    ('237.25', 800),
]
ASKS = [
    ('238.50', 300),
    ('238.60', 450),
    ('238.75', 600),
    ('239.00', 1000),
    ('239.25', 800),
]


class OrderTheBookCoversExample:
    """Estimates two orders and prints their figures.

    Attributes:
        bids (list): The bid levels.
        asks (list): The ask levels.
    """

    def __init__(self):
        """Builds the book.

        Returns:
            None: This method returns nothing.
        """
        self.bids = self.levels(BIDS)
        self.asks = self.levels(ASKS)

    def levels(self, side):
        """One side of the book with decimal prices.

        Args:
            side (list): Tuples of price (str) and quantity (int).

        Returns:
            list: Tuples of price (decimal.Decimal) and quantity (int).
        """
        levels = []
        for price, quantity in side:
            levels.append((decimal.Decimal(price), quantity))
        return levels

    def run(self):
        """Prints each estimate.

        Returns:
            None: This method returns nothing.
        """
        for transaction_type, quantity in [('BUY', 1200), ('SELL', 400)]:
            estimate = PreTradeEstimate(transaction_type, quantity, self.bids, self.asks)
            print(f'{transaction_type} {quantity}: mid {estimate.mid()}, touch {estimate.touch()}, priceable {estimate.is_priceable()}, covered {estimate.is_covered_by_book()}')
            print(f'  half spread {estimate.half_spread()} + book walk {estimate.book_walk()} + beyond book {estimate.beyond_book()} = {estimate.total()} a unit')
            print(f'  average price {estimate.average_price()}, {estimate.basis_points()} bps, {estimate.rupees()} rupees, side {estimate.side()}')


if __name__ == '__main__':
    OrderTheBookCoversExample().run()
