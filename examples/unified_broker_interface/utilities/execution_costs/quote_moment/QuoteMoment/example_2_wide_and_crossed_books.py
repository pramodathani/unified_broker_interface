"""Compares the half spread of a liquid option, an illiquid far strike and a book that is briefly crossed.

The same order can cost very different amounts to cross the spread depending on the instrument: a tick or two on a near strike, many rupees on a far one. A crossed book, where the best bid is above the best ask for a moment, gives a negative half spread, which the measurement keeps rather than hides. This program builds the quotes by hand, so it reads no database.

Notice the far strike's half spread is twenty times the near strike's, and the crossed book's is below zero.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/quote_moment/QuoteMoment/example_2_wide_and_crossed_books.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)

QUOTES = [
    (
        'near strike',
        '238.00',
        '238.10',
    ),
    (
        'far strike',
        '4.00',
        '6.00',
    ),
    (
        'crossed book',
        '238.15',
        '238.10',
    ),
]


class WideAndCrossedBooksExample:
    """Prints the half spread of three quotes.

    Attributes:
        received (datetime.datetime): When every quote was received.
    """

    def __init__(self):
        """Builds the example.

        Returns:
            None: This method returns nothing.
        """
        self.received = datetime.datetime(2026, 10, 6, 4, 45, 0, tzinfo=datetime.timezone.utc)

    def run(self):
        """Prints each quote's mid-price and half spread.

        Returns:
            None: This method returns nothing.
        """
        for name, bid, ask in QUOTES:
            quote = QuoteMoment(self.received, decimal.Decimal(bid), decimal.Decimal(ask))
            print(f'{name}: mid {quote.mid()}, half spread {quote.half_spread()}')


if __name__ == '__main__':
    WideAndCrossedBooksExample().run()
