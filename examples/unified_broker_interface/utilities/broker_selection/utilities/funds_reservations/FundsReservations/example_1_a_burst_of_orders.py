"""Reserves the margin of three orders sent to one broker within a second, and shows what is still held.

A broker's free cash is read every half second, so orders arriving together would all see the same balance. `FundsReservations` remembers the margin of each order just chosen for a broker, and the funds check subtracts it from the broker's balance until a funds reading taken after it has settled. This program uses fixed moments on 2026-09-30, so its output never changes.

Notice that while the latest funds reading is from before the orders, all 30,000 is held, and it would be subtracted from the broker's balance.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/funds_reservations/FundsReservations/example_1_a_burst_of_orders.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.broker_selection.utilities.funds_reservations import (
    FundsReservations,
)


class ABurstOfOrdersExample:
    """Reserves three orders' margin and reads the total held.

    Attributes:
        reservations (FundsReservations): The ledger, with a two-second settle time.
        start (datetime.datetime): When the first order was chosen.
    """

    def __init__(self):
        """Builds the ledger.

        Returns:
            None: This method returns nothing.
        """
        self.reservations = FundsReservations(2)
        self.start = datetime.datetime(2026, 9, 30, 10, 40, 0)

    def run(self):
        """Reserves 10,000 three times, a tenth of a second apart, and prints what is held.

        Returns:
            None: This method returns nothing.
        """
        for position in range(3):
            moment = self.start + datetime.timedelta(milliseconds=100 * position)
            self.reservations.reserve('zerodha', decimal.Decimal('10000'), moment)
            print(f'Reserved 10,000 at {moment:%H:%M:%S.%f}')
        funds_read_at = self.start - datetime.timedelta(milliseconds=200)
        print(f'Held against funds read at {funds_read_at:%H:%M:%S.%f}: {self.reservations.reserved("zerodha", funds_read_at)}')
        print(f'Held at a broker with none: {self.reservations.reserved("dhan", funds_read_at)}')


if __name__ == '__main__':
    ABurstOfOrdersExample().run()
