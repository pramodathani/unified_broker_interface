"""Works out the mid-price and half spread of a NIFTY option quoted at 238.00 bid and 238.50 ask.

The mid-price is the reference every execution cost is measured from, and the half spread is what an order pays to cross from the mid-price to the other side of the book. This program builds the quote by hand, so it reads no database.

Notice that buying 65 units at the ask costs 16.25 rupees more than the mid-price before the price has moved at all.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/quote_moment/QuoteMoment/example_1_mid_and_half_spread.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)


class MidAndHalfSpreadExample:
    """Prints one quote's mid-price and half spread.

    Attributes:
        quote (QuoteMoment): The quote.
    """

    def __init__(self):
        """Builds the quote.

        Returns:
            None: This method returns nothing.
        """
        received = datetime.datetime(2026, 10, 6, 4, 45, 0, tzinfo=datetime.timezone.utc)
        self.quote = QuoteMoment(received, decimal.Decimal('238.00'), decimal.Decimal('238.50'))

    def run(self):
        """Prints the figures.

        Returns:
            None: This method returns nothing.
        """
        print(f'Bid {self.quote.bid}, ask {self.quote.ask}')
        print(f'Mid-price: {self.quote.mid()}')
        print(f'Half spread: {self.quote.half_spread()}')
        print(f'Crossing the spread for 65 units: {self.quote.half_spread() * 65} rupees')


if __name__ == '__main__':
    MidAndHalfSpreadExample().run()
