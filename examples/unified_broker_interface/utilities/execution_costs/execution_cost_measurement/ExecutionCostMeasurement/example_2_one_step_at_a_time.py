"""Takes the measurement's steps one at a time against a stand-in database, then writes the result.

`measure` is a short series of steps: read the events, fold them into filled legs, read the segments, and find each leg's quotes. This program calls each step itself, shows that a quote older than 60 seconds is treated as missing, and finishes with `write`, which applies the table's file, deletes the days measured and inserts the rows in one transaction. The stand-in database answers the queries and records the statements, so no PostgreSQL is used.

Notice that the write sends exactly three statements and commits once, which is why running the script twice leaves the same rows.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/execution_cost_measurement/ExecutionCostMeasurement/example_2_one_step_at_a_time.py
"""

import datetime
import decimal
import logging

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.execution_cost_measurement import (
    ExecutionCostMeasurement,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
CRUDE = '3e0d6c21-8b4f-4a9e-b7d2-5c1f0a9e6d43'


class OneStepAtATimeExample:
    """Runs each step of a measurement by hand and then writes it.

    Attributes:
        database (StandInExecutionDatabase): The stand-in database.
        measurement (ExecutionCostMeasurement): The measurement.
    """

    def __init__(self):
        """Builds the database and the measurement.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInExecutionDatabase()
        self.database.segments[CRUDE] = 'mcx_commodity_futures'
        self.database.add_tick(CRUDE, self.at(21, 0, 0), '5210', '5211')
        self.database.add_event(self.at(21, 0, 0, 100), 'crude', 'parent_received', instrument_id=CRUDE)
        self.database.add_event(self.at(21, 0, 0, 200), 'crude', 'leg_requested', leg_id='1', leg_role='entry', broker='zerodha', instrument_id=CRUDE, transaction_type='BUY', quantity=100)
        self.database.add_event(self.at(21, 0, 0, 300), 'crude', 'leg_answered', leg_id='1', outcome='accepted')
        self.database.add_event(self.at(21, 0, 1), 'crude', 'leg_update', leg_id='1', filled_quantity=1, average_price='5212')
        self.measurement = ExecutionCostMeasurement(self.database.connect, logging.getLogger('example'))

    def at(self, hour, minute, second, millisecond=0):
        """A moment on 6 October 2026 in India's time zone.

        Args:
            hour (int): The hour.
            minute (int): The minute.
            second (int): The second.
            millisecond (int): The millisecond.

        Returns:
            datetime.datetime: The moment.
        """
        return datetime.datetime(2026, 10, 6, hour, minute, second, millisecond * 1000, INDIA)

    def run(self):
        """Runs the steps and the write, printing what each returns.

        Returns:
            None: This method returns nothing.
        """
        start, end = self.measurement.day_bounds(datetime.date(2026, 10, 6), 1)
        print(f'Days: {start.isoformat()} to {end.isoformat()}')
        connection = self.database.connect()
        with connection.cursor() as cursor:
            rows = self.measurement.read_events(cursor, start, end)
            print(f'Event rows read: {len(rows)}')
            legs = self.measurement.filled_legs(rows, start, end)
            print(f'Filled legs: {len(legs)}, sent at {self.measurement.sent_at_of(legs[0]).time()}')
            segments = self.measurement.read_segments(cursor, [CRUDE])
            print(f'Segment: {segments[CRUDE]}, securities market {self.measurement.is_securities_market(segments[CRUDE])}')
            recent = self.measurement.quote_at(cursor, CRUDE, self.at(21, 0, 0, 200))
            print(f'Quote when sent: {recent.bid} / {recent.ask}')
            print(f'Quote two minutes later: {self.measurement.quote_at(cursor, CRUDE, self.at(21, 2, 0))}')
            cost = self.measurement.cost_of(cursor, legs[0], segments[CRUDE])
            print(f'Cost: {cost.basis_points(cost.total())} bps, rupees {cost.total_rupees()}')
        written = self.measurement.write(start, end, [cost])
        print(f'Rows written: {written}, statements {self.database.statements[-3:]}, transactions {self.database.transactions[-1:]}')
        figures = [
            decimal.Decimal('1'),
            decimal.Decimal('2'),
            decimal.Decimal('6'),
        ]
        print(f'Median and mean of 1, 2 and 6 basis points: {self.measurement.median(figures)}, {self.measurement.mean(figures)}')


if __name__ == '__main__':
    OneStepAtATimeExample().run()
