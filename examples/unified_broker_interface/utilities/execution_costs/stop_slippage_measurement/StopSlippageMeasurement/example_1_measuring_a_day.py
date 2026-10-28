"""Measures a scripted day of three fired stops and prints the summary the nightly script prints.

`StopSlippageMeasurement` reads the order engine's event log and follows every protective stop that fired to the fill that closed its position. This program scripts the day on a stand-in database, the way the offline suite does, so it needs no PostgreSQL: one stop that filled itself, one that the strategy cancelled and closed with its own sell three seconds later, and one whose close never appeared.

Notice that the second stop is counted with the close the strategy made, 194.60, which slipped further than the stop that filled itself, and that the third is counted as unresolved and left out of the slips.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_slippage_measurement/StopSlippageMeasurement/example_1_measuring_a_day.py
"""

import datetime
import logging

from test_runs.stop_slippage_stand_ins import StandInStopDatabase
from unified_broker_interface.utilities.execution_costs.stop_slippage_measurement import (
    StopSlippageMeasurement,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = '065e67b5-b3f8-5374-a0bb-4ddc7786338d'


class MeasuringADayExample:
    """Measures and summarises the scripted day.

    Attributes:
        database (StandInStopDatabase): The scripted events.
        measurement (StopSlippageMeasurement): The measurement.
    """

    def __init__(self):
        """Scripts the day and builds the measurement.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInStopDatabase()
        self.database.segments[OPTION] = 'nse_equity_index_options'
        self.database.add_stop(datetime.datetime(2026, 10, 19, 13, 26, 25, tzinfo=INDIA), 'filled-itself', OPTION, '173.85', fill_price='173.25')
        self.database.add_stop(datetime.datetime(2026, 10, 19, 13, 12, 3, tzinfo=INDIA), 'closed-by-the-strategy', OPTION, '196.15')
        self.database.add_order(datetime.datetime(2026, 10, 19, 13, 12, 6, tzinfo=INDIA), 'strategy-sell', OPTION, 'SELL', fill_price='194.60')
        self.database.add_stop(datetime.datetime(2026, 10, 19, 13, 17, 40, tzinfo=INDIA), 'close-not-found', OPTION, '161.25')
        self.measurement = StopSlippageMeasurement(self.database.connect, logging.getLogger('example'))

    def run(self):
        """Prints every stop and the summary.

        Returns:
            None: This method returns nothing.
        """
        start, end = self.measurement.day_bounds(datetime.date(2026, 10, 19), 1)
        print(f'Measuring from {start.isoformat()} to {end.isoformat()}')
        for outcome in self.measurement.measure(start, end):
            print(f'{outcome.fired_at:%H:%M:%S} {outcome.parent_order_id}: trigger {outcome.trigger_price}, closed by {outcome.closed_by}, slip {outcome.slip()}')
        outcomes = self.measurement.measure(start, end)
        for line in self.measurement.summary(outcomes):
            print(line)


if __name__ == '__main__':
    MeasuringADayExample().run()
