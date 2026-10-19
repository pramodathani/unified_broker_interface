"""Reads the slip allowance from a stand-in for `unified.stop_slippage`, where one side has enough stops and the other does not.

`read` takes the measured slips of the stops that fired in the last 20 days and groups them by segment and side. A segment and side needs at least 30 stops before it has an allowance, so a tripwire for the other side falls back to the live spread. This program reads from a stand-in database, so it needs no PostgreSQL.

Notice that the sell side, with 35 stops, has an allowance, while the buy side, with 5, has None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_slip_allowance/StopSlipAllowance/example_2_reading_the_table.py
"""

import datetime
import decimal

from test_runs.stop_slippage_stand_ins import StandInStopDatabase
from unified_broker_interface.utilities.execution_costs.stop_slip_allowance import (
    StopSlipAllowance,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
SEGMENT = 'nse_equity_index_options'


class ReadingTheTableExample:
    """Reads and prints both sides' allowances.

    Attributes:
        database (StandInStopDatabase): The stand-in table.
        allowance (StopSlipAllowance): The allowance, empty until read.
    """

    def __init__(self):
        """Fills the stand-in table with 35 sell slips and 5 buy slips.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInStopDatabase()
        for index in range(35):
            self.database.slips.append((SEGMENT, 'SELL', decimal.Decimal(index * 2)))
        for index in range(5):
            self.database.slips.append((SEGMENT, 'BUY', decimal.Decimal(index)))
        self.allowance = StopSlipAllowance()

    def run(self):
        """Reads the table and prints each side.

        Returns:
            None: This method returns nothing.
        """
        print(f'Before reading: {self.allowance.stop_count(SEGMENT, "SELL")} sell stops')
        self.allowance.read(self.database.connect, datetime.datetime(2026, 10, 19, 23, 50, tzinfo=INDIA))
        for side in ('SELL', 'BUY'):
            print(f'{side}: {self.allowance.stop_count(SEGMENT, side)} stops, allowance {self.allowance.basis_points(SEGMENT, side)} bps')


if __name__ == '__main__':
    ReadingTheTableExample().run()
