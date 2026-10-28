"""Saves the orders of 19 October 2026 from a stand-in of the combined orders document, and prints the summary the nightly script prints.

A `DailyOrderSnapshot` reads `unified:orders:orders`, which Redis drops at the next 06:00 IST, picks the orders placed on a day, and writes their final state to `unified.daily_orders`. This program uses the stand-in Redis and database of the offline suite, so it needs neither: the document holds Flattrade's stop order 26101900306429, which filled at 160.45 while the strategy was cancelling it, a rejected sell, a Wisdom Capital cancellation and an order of the day before.

Notice that the order of 18 October is left out of the 19th's rows, and that the write is a delete and an insert with parameters, so a carriage return in a message needs no escaping.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_history/daily_order_snapshot/DailyOrderSnapshot/example_1_saving_a_day.py
"""

import json
import logging

from test_runs.daily_orders import DailyOrdersSuite, StandInCache, StandInSnapshotDatabase
from unified_broker_interface.utilities.order_history.daily_order_snapshot import (
    DailyOrderSnapshot,
)


class SavingADayExample:
    """Saves and summarises one day.

    Attributes:
        database (StandInSnapshotDatabase): The stand-in database.
        snapshot (DailyOrderSnapshot): The snapshot.
    """

    def __init__(self):
        """Builds the stand-ins and the snapshot.

        Returns:
            None: This method returns nothing.
        """
        document = DailyOrdersSuite().document()
        cache = StandInCache({'unified:orders:orders': json.dumps(document).encode()})
        self.database = StandInSnapshotDatabase()
        self.snapshot = DailyOrderSnapshot(cache, self.database.connect, logging.getLogger('example'))

    def run(self):
        """Reads the document, saves each day and prints what was saved.

        Returns:
            None: This method returns nothing.
        """
        document = self.snapshot.read_document()
        for trading_day in self.snapshot.trading_days(document):
            orders = self.snapshot.orders_of_day(document, trading_day)
            written = self.snapshot.write(trading_day, orders)
            print(f'{trading_day}: wrote {written} orders')
            for line in self.snapshot.summary(orders):
                print(f'  {line["broker"]}: {line["orders"]} orders, {line["filled"]} filled, worth {line["filled_value"]:,.2f}')
        print(f'Statements: {self.database.statements}')
        print(f'Days deleted before writing: {self.database.deleted}')
        print(f'First order of 19 October saved: {self.database.written[1][2]}, filled {self.database.written[1][15]} at {self.database.written[1][18]}')
        print(f'The 19th is the day of {self.snapshot.trading_day_of(document["orders"][0])}; no time gives {self.snapshot.trading_day_of({})}')


if __name__ == '__main__':
    SavingADayExample().run()
