"""Estimates a buy of 5,000 units when the book shows only 3,150, using the square-root model for the rest.

The 1,850 units left beyond the last visible level are counted at that level's price, and the square-root model adds coefficient × daily volatility × mid-price × √(1,850 ÷ average daily volume) a unit for them. The instrument here moves about 9.8% a day and trades a million units, and the coefficient is the textbook 1.0, which has not been fitted to real orders. Without the volatility the model cannot run, and the estimate is left empty rather than guessed. This program builds everything by hand, so it reads no database.

Notice that the model adds 0.37 a unit to the whole order, and that the version without daily figures has no total.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/pre_trade_estimate/PreTradeEstimate/example_2_an_order_too_big_for_the_book.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.daily_liquidity import (
    DailyLiquidity,
)
from unified_broker_interface.utilities.execution_costs.pre_trade_estimate import (
    PreTradeEstimate,
)

BIDS = [
    ('238.00', 300),
    ('237.90', 450),
]
ASKS = [
    ('238.50', 300),
    ('238.60', 450),
    ('238.75', 600),
    ('239.00', 1000),
    ('239.25', 800),
]


class OrderTooBigForTheBookExample:
    """Estimates one large order with and without the model's inputs.

    Attributes:
        bids (list): The bid levels.
        asks (list): The ask levels.
        liquidity (DailyLiquidity): Closes alternating between 100 and 110, and a million units a day.
    """

    def __init__(self):
        """Builds the book and the daily figures.

        Returns:
            None: This method returns nothing.
        """
        self.bids = []
        for price, quantity in BIDS:
            self.bids.append((decimal.Decimal(price), quantity))
        self.asks = []
        for price, quantity in ASKS:
            self.asks.append((decimal.Decimal(price), quantity))
        closes = []
        for index in range(21):
            if index % 2 == 0:
                closes.append(decimal.Decimal(100))
            else:
                closes.append(decimal.Decimal(110))
        self.liquidity = DailyLiquidity(closes, [1000000] * 20)

    def run(self):
        """Prints the estimate with and without the model.

        Returns:
            None: This method returns nothing.
        """
        estimate = PreTradeEstimate('BUY', 5000, self.bids, self.asks, self.liquidity, decimal.Decimal('1.0'))
        print(f'Covered by the book: {estimate.is_covered_by_book()}, left over: {estimate.walk.remaining_quantity()}')
        print(f'Model impact on the left-over units: {estimate.remainder_impact()} a unit')
        print(f'half spread {estimate.half_spread()} + book walk {estimate.book_walk()} + beyond book {estimate.beyond_book()} = {estimate.total()} a unit')
        print(f'Average price {estimate.average_price()}, {estimate.basis_points()} bps, {estimate.rupees()} rupees')
        without = PreTradeEstimate('BUY', 5000, self.bids, self.asks)
        print(f'Without daily figures: impact {without.remainder_impact()}, total {without.total()}')
        print(f"A unit cost of -0.00004 is written as {estimate.rounded(decimal.Decimal('-0.00004'))}")


if __name__ == '__main__':
    OrderTooBigForTheBookExample().run()
