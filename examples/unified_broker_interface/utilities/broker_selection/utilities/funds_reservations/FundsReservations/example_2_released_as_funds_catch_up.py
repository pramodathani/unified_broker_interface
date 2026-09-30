"""Shows reservations being released as later funds readings arrive.

A reservation is dropped once the broker's funds were read more than the settle time after it was made, because by then the balance already shows the order, or the order was refused and never used the money. No answer from the broker and no timer are needed. This program reserves two orders a second apart and reads the ledger against three funds readings.

Notice that each reservation disappears on its own, two seconds after it was made, and that a reading with no known time keeps everything.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/funds_reservations/FundsReservations/example_2_released_as_funds_catch_up.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.broker_selection.utilities.funds_reservations import (
    FundsReservations,
)


class ReleasedAsFundsCatchUpExample:
    """Reserves two orders and reads the ledger as time passes.

    Attributes:
        reservations (FundsReservations): The ledger, with a two-second settle time.
        start (datetime.datetime): When the first order was chosen.
    """

    def __init__(self):
        """Builds the ledger with two reservations.

        Returns:
            None: This method returns nothing.
        """
        self.reservations = FundsReservations(2)
        self.start = datetime.datetime(2026, 9, 30, 10, 40, 0)
        self.reservations.reserve('dhan', decimal.Decimal('7962.50'), self.start)
        self.reservations.reserve('dhan', decimal.Decimal('1017.70'), self.start + datetime.timedelta(seconds=1))

    def run(self):
        """Prints what is held against a reading with no time, then against readings 1.5, 2.5 and 3.5 seconds later.

        Returns:
            None: This method returns nothing.
        """
        print(f'Funds read at an unknown time: {self.reservations.reserved("dhan", None)} held')
        for seconds in [1.5, 2.5, 3.5]:
            funds_read_at = self.start + datetime.timedelta(seconds=seconds)
            print(f'Funds read {seconds} seconds after the first order: {self.reservations.reserved("dhan", funds_read_at)} held')


if __name__ == '__main__':
    ReleasedAsFundsCatchUpExample().run()
