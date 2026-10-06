"""Measures one day of fills against a stand-in database, the way the nightly script does, and prints each broker's figures.

The stand-in holds the engine events of two parents and a handful of stored ticks. The first parent bought a NIFTY option at Flattrade and then sold it with a stop; the second sold the same option at Zerodha. `measure` reads the events, keeps the legs that filled, reads each instrument's segment, and finds the quote at each leg's decision, send and answer. The stand-in answers those queries from what this program scripted, so no PostgreSQL is used.

Notice that the stop is measured from when it was sent, five minutes after its parent arrived, so it has no delay.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/execution_cost_measurement/ExecutionCostMeasurement/example_1_measuring_a_day.py
"""

import datetime
import logging

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.execution_cost_measurement import (
    ExecutionCostMeasurement,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = 'b51c2f7e-5a0d-4c43-9e11-0f6a2d7c8b19'


class MeasuringADayExample:
    """Scripts a day, measures it and prints the results.

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
        self.database.segments[OPTION] = 'nse_equity_index_options'
        self.database.add_tick(OPTION, self.at(10, 14, 59, 900), '238.00', '238.50')
        self.database.add_tick(OPTION, self.at(10, 15, 0, 150), '238.10', '238.60')
        self.database.add_tick(OPTION, self.at(10, 15, 0, 250), '238.20', '238.70')
        self.database.add_tick(OPTION, self.at(10, 19, 59, 950), '240.00', '240.40')
        self.add_parent('first', 'flattrade', 'BUY', '238.90')
        self.database.add_event(self.at(10, 20, 0, 0), 'first', 'leg_requested', leg_id='2', leg_role='stop', broker='flattrade', instrument_id=OPTION, transaction_type='SELL', quantity=65)
        self.database.add_event(self.at(10, 20, 0, 80), 'first', 'leg_answered', leg_id='2', outcome='accepted')
        self.database.add_event(self.at(10, 20, 1, 0), 'first', 'leg_update', leg_id='2', filled_quantity=65, average_price='239.90')
        self.add_parent('second', 'zerodha', 'SELL', '238.05')
        self.measurement = ExecutionCostMeasurement(self.database.connect, logging.getLogger('example'))

    def at(self, hour, minute, second, millisecond):
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

    def add_parent(self, parent_order_id, broker, transaction_type, average_price):
        """Scripts a parent arriving at 10:15 and its first leg filling at once.

        Args:
            parent_order_id (str): The parent.
            broker (str): The broker the leg went to.
            transaction_type (str): `BUY` or `SELL`.
            average_price (str): The fill price.

        Returns:
            None: This method returns nothing.
        """
        self.database.add_event(self.at(10, 15, 0, 0), parent_order_id, 'parent_received', instrument_id=OPTION)
        self.database.add_event(self.at(10, 15, 0, 200), parent_order_id, 'leg_requested', leg_id='1', leg_role='entry', broker=broker, instrument_id=OPTION, transaction_type=transaction_type, quantity=65)
        self.database.add_event(self.at(10, 15, 0, 300), parent_order_id, 'leg_answered', leg_id='1', outcome='accepted')
        self.database.add_event(self.at(10, 15, 0, 400), parent_order_id, 'leg_update', leg_id='1', filled_quantity=65, average_price=average_price)

    def run(self):
        """Measures the day and prints each leg and each broker.

        Returns:
            None: This method returns nothing.
        """
        start, end = self.measurement.day_bounds(datetime.date(2026, 10, 6), 1)
        costs = self.measurement.measure(start, end)
        for cost in costs:
            row = cost.row()
            print(f"{row['parent_order_id']} leg {row['leg_id']} ({row['broker']}, {row['transaction_type']}): decided {row['decided_at'].time()}, delay {row['delay_cost']}, latency {row['latency_cost']}, total {row['total_cost']} = {row['total_cost_basis_points']} bps = {row['total_cost_rupees']} rupees")
        for line in self.measurement.summary(costs):
            print(line)


if __name__ == '__main__':
    MeasuringADayExample().run()
