"""Shows that a new margin rate table is empty, and when it would next reload.

A process builds its `MarginRateTable` when the order blueprint is imported, before any database is needed, so the table starts empty and the lowest-cost selector's funds check is off. `start` reads `unified.margin_rates` and starts a thread that reloads it at every 06:00 IST. This program does not call `start`, so it needs no database; it only asks how long the reload thread would wait from two moments on 2026-09-30.

Notice that at 05:00 the next reload is one hour away, and at 10:40 it is the next morning, 19 hours and 20 minutes away.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_rate_table/MarginRateTable/example_2_empty_until_started.py
"""

import datetime
import logging

from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRateTable,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)


class EmptyUntilStartedExample:
    """Prints the empty table's state and two reload waits.

    Attributes:
        table (MarginRateTable): The table, never started.
    """

    def __init__(self):
        """Builds the empty table.

        Returns:
            None: This method returns nothing.
        """
        self.table = MarginRateTable(logging.getLogger('example'))

    def run(self):
        """Prints whether rows are loaded, a lookup, and the waits until the next reload.

        Returns:
            None: This method returns nothing.
        """
        print(f'Loaded: {self.table.is_loaded()}')
        print(f'NIFTY futures rate: {self.table.rate("nse_equity_index_futures", "NIFTY")}')
        moments = [
            datetime.datetime(2026, 9, 30, 5, 0, tzinfo=INDIA),
            datetime.datetime(2026, 9, 30, 10, 40, tzinfo=INDIA),
        ]
        for moment in moments:
            seconds = self.table.seconds_until_reload(moment)
            print(f'At {moment:%H:%M} the next reload is {seconds / 3600:.2f} hours away')


if __name__ == '__main__':
    EmptyUntilStartedExample().run()
