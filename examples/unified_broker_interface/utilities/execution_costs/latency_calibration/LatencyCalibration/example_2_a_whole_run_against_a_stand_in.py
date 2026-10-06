"""Runs a whole calibration against a stand-in database: read the window, work out the figures, and write them.

`measure` reads the last twenty days of `unified.order_execution_costs`, and `write` updates `unified.broker_order_costs` for every broker with at least one figure, passing None for the rest so the table keeps what it held. A broker that has measured legs but no row in the cost table is warned about and not written. The stand-in database answers the read from scripted rows and records the updates, so no PostgreSQL is used.

Notice that only Groww is updated: Kotak has too few legs, and `newbroker` has no row in the cost table.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/latency_calibration/LatencyCalibration/example_2_a_whole_run_against_a_stand_in.py
"""

import datetime
import decimal
import logging
import sys

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.latency_calibration import (
    LatencyCalibration,
)


class WholeRunExample:
    """Scripts the database, runs the calibration and prints what was written.

    Attributes:
        database (StandInExecutionDatabase): The stand-in database.
        calibration (LatencyCalibration): The calibration.
    """

    def __init__(self):
        """Builds the database and the calibration.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInExecutionDatabase()
        self.database.cost_table_brokers = [
            'groww',
            'kotak',
        ]
        self.add_rows('groww', 'nse_equities', 'CNC', 40, '0.80', '45')
        self.add_rows('kotak', 'nse_equities', 'MIS', 12, '0.00', '120')
        self.add_rows('newbroker', 'nse_equity_options', 'MIS', 35, '0.10', '30')
        logger = logging.getLogger('example')
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.propagate = False
        self.calibration = LatencyCalibration(self.database.connect, logger)

    def add_rows(self, broker, segment, product, count, latency_cost, answer_milliseconds):
        """Adds identical measured legs for one broker.

        Args:
            broker (str): The broker.
            segment (str): The segment.
            product (str): The product.
            count (int): How many legs.
            latency_cost (str): Each leg's latency cost in basis points.
            answer_milliseconds (str): Each leg's answer time.

        Returns:
            None: This method returns nothing.
        """
        for index in range(count):
            self.database.cost_rows.append((broker, segment, product, decimal.Decimal(latency_cost), decimal.Decimal(answer_milliseconds)))

    def run(self):
        """Runs the calibration and prints the window, the updates and the count.

        Returns:
            None: This method returns nothing.
        """
        now = datetime.datetime(2026, 10, 6, 18, 20, tzinfo=datetime.timezone.utc)
        since = self.calibration.window_start(now)
        print(f'Window starts {since.isoformat()}')
        brokers = self.calibration.measure(since)
        updated = self.calibration.write(brokers)
        for parameters in self.database.updates:
            print(f'UPDATE {parameters[-1]}: intraday {parameters[0]}, delivery {parameters[1]}, fno {parameters[2]}, answer {parameters[3]} ms')
        print(f'Rows updated: {updated}, transactions {self.database.transactions}')


if __name__ == '__main__':
    WholeRunExample().run()
