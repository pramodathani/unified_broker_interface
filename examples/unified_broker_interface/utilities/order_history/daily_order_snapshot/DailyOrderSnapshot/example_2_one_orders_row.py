"""Turns one order of the combined document into a row of `unified.daily_orders`, and shows how messy values are read.

`row` copies an order's fields into the table's columns: quantities become whole numbers with `whole`, prices become decimals with `number`, and timestamps become moments with `moment`, each answering None for a value it cannot read rather than failing the night's write. The whole order is kept as JSON beside the columns. This program needs no Redis or database.

Notice that a quantity a broker sent as 65.0 is stored as 65, and that the engine parent id ties the broker's order back to the stop that sent it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_history/daily_order_snapshot/DailyOrderSnapshot/example_2_one_orders_row.py
"""

import datetime
import logging

from unified_broker_interface.utilities.order_history.daily_order_snapshot import (
    DailyOrderSnapshot,
)


class OneOrdersRowExample:
    """Prints one order's row and the readers' answers.

    Attributes:
        snapshot (DailyOrderSnapshot): A snapshot with no Redis or database, which `row` does not need.
    """

    def __init__(self):
        """Builds the snapshot.

        Returns:
            None: This method returns nothing.
        """
        self.snapshot = DailyOrderSnapshot(None, None, logging.getLogger('example'))

    def run(self):
        """Prints the row's main columns and some readings.

        Returns:
            None: This method returns nothing.
        """
        order = {
            'broker': 'flattrade',
            'order_id': 26101900306429,
            'status': 'COMPLETE',
            'transaction_type': 'SELL',
            'quantity': 65.0,
            'filled_quantity': '65',
            'average_price': 160.45,
            'order_timestamp': '2026-10-19T13:17:41+05:30',
            'engine_parent_id': '6b7bf82f-2c16-453f-b812-902216e84f4f',
        }
        row = self.snapshot.row(order, datetime.date(2026, 10, 19))
        for column in ('trading_day', 'broker', 'order_id', 'quantity', 'filled_quantity', 'average_price', 'order_timestamp', 'engine_parent_id'):
            print(f'{column}: {row[column]!r}')
        print(f'whole(10.0) = {self.snapshot.whole(10.0)}, whole("x") = {self.snapshot.whole("x")}')
        print(f'number("160.45") = {self.snapshot.number("160.45")}, number("") = {self.snapshot.number("")}')
        print(f'moment("yesterday") = {self.snapshot.moment("yesterday")}')


if __name__ == '__main__':
    OneOrdersRowExample().run()
