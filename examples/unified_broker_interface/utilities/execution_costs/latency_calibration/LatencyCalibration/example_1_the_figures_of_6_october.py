"""Turns rows like those measured up to 6 October 2026 into each broker's latency figures, as the nightly script does.

`brokers_from` sorts every row into the lowest-cost selector's categories and gathers it under its broker. This program feeds in rows shaped like the real ones: Flattrade with F&O and intraday legs, Zerodha with F&O legs, and Dhan with too few legs to measure. The rows are built by hand, so no database is read.

Notice that Flattrade's F&O latency cost of -0.44 and Zerodha's of 1.35 basis points match the real run of that night, and that Dhan's figures are all None, so its row in the cost table would be left as it is.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/latency_calibration/LatencyCalibration/example_1_the_figures_of_6_october.py
"""

import decimal
import logging

from unified_broker_interface.utilities.execution_costs.broker_latency import (
    CATEGORIES,
)
from unified_broker_interface.utilities.execution_costs.latency_calibration import (
    LatencyCalibration,
)

BROKER_LEGS = [
    (
        'flattrade',
        'nse_equity_index_options',
        'MIS',
        72,
        '-4.40',
        '54',
    ),
    (
        'flattrade',
        'nse_equities',
        'MIS',
        101,
        '0',
        '54',
    ),
    (
        'zerodha',
        'nse_equity_index_options',
        'NRML',
        37,
        '13.50',
        '67',
    ),
    (
        'dhan',
        'nse_equities',
        'MIS',
        25,
        '0',
        '70',
    ),
]


class FiguresOfSixOctoberExample:
    """Builds the rows and prints each broker's figures.

    Attributes:
        calibration (LatencyCalibration): The calibration, never asked to read or write the database.
    """

    def __init__(self):
        """Builds the calibration.

        Returns:
            None: This method returns nothing.
        """
        self.calibration = LatencyCalibration(None, logging.getLogger('example'))

    def rows(self):
        """Rows of the execution cost table, with one leg of each group carrying all of its group's price move.

        Returns:
            list: Tuples of broker, segment, product, latency cost in basis points and answer time in milliseconds.
        """
        rows = []
        for broker, segment, product, count, first_cost, answer in BROKER_LEGS:
            for index in range(count):
                latency_cost = decimal.Decimal('0')
                if index == 0:
                    latency_cost = decimal.Decimal(first_cost) * count / 10
                rows.append((broker, segment, product, latency_cost, decimal.Decimal(answer)))
        return rows

    def run(self):
        """Prints each broker's leg counts, latency costs and answer time.

        Returns:
            None: This method returns nothing.
        """
        print(f"An index option bought MIS is {self.calibration.category('nse_equity_index_options', 'MIS')}, a share bought CNC is {self.calibration.category('nse_equities', 'CNC')}")
        for broker in self.calibration.brokers_from(self.rows()):
            figures = []
            for category in CATEGORIES:
                figures.append(f'{category} {broker.leg_count(category)} legs {broker.latency_cost(category)} bps')
            print(f"{broker.broker_name}: {', '.join(figures)}, answer {broker.typical_answer_milliseconds()} ms")


if __name__ == '__main__':
    FiguresOfSixOctoberExample().run()
