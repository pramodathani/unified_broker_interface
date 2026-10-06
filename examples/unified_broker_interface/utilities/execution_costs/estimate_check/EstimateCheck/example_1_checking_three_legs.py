"""Checks the estimate against three measured legs held in a stand-in database, the way the estimate check script does.

For each leg, `compare` rebuilds the book at its decision from the stored ticks, reads the daily bars before that day, estimates the cost of crossing, and sets it beside what the leg actually cost. The three legs are a market buy, which crossed; a stop sell, which waited for its trigger and so counts as resting; and a limit whose instrument has no stored book. The stand-in database answers every query from scripted rows, so no PostgreSQL is used.

Notice that the market buy was estimated at 16.00 basis points and cost 16.79, and that the leg with no book has no estimate.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/estimate_check/EstimateCheck/example_1_checking_three_legs.py
"""

import datetime
import decimal
import logging

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.estimate_check import (
    EstimateCheck,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = 'b51c2f7e-5a0d-4c43-9e11-0f6a2d7c8b19'
BIDS = [
    ('238.00', 300),
    ('237.90', 450),
]
ASKS = [
    ('238.50', 300),
    ('238.60', 450),
    ('238.75', 600),
]


class CheckingThreeLegsExample:
    """Scripts three legs, checks them and prints the comparison.

    Attributes:
        database (StandInExecutionDatabase): The stand-in database.
        check (EstimateCheck): The check.
    """

    def __init__(self):
        """Builds the database and the check.

        Returns:
            None: This method returns nothing.
        """
        decided_at = datetime.datetime(2026, 10, 6, 10, 15, 0, tzinfo=INDIA)
        self.database = StandInExecutionDatabase()
        self.database.coefficient_rows = [
            ('securities', decimal.Decimal('1.0'), None),
        ]
        self.database.add_book(OPTION, decided_at - datetime.timedelta(seconds=1), BIDS, ASKS)
        for day in range(25):
            bar_time = datetime.datetime(2026, 9, 1, tzinfo=INDIA) + datetime.timedelta(days=day)
            self.database.daily_bars.setdefault(OPTION, []).append((bar_time, decimal.Decimal(240 + day % 3), 400000))
        mid = decimal.Decimal('238.25')
        self.database.estimate_legs = [
            ('first', '1', 'zerodha', OPTION, 'nse_equity_index_options', 'BUY', 'MARKET', None, 1200, decided_at, mid, decimal.Decimal('0.25'), decimal.Decimal('0.15')),
            ('first', '2', 'zerodha', OPTION, 'nse_equity_index_options', 'SELL', 'SL', decimal.Decimal('238.10'), 65, decided_at, mid, decimal.Decimal('0.25'), decimal.Decimal('-3.00')),
            ('second', '1', 'flattrade', 'f00dfeed-0000-4000-8000-000000000000', 'nse_equity_options', 'BUY', 'LIMIT', decimal.Decimal('50'), 65, decided_at, decimal.Decimal('50'), decimal.Decimal('0.05'), decimal.Decimal('0')),
        ]
        self.check = EstimateCheck(self.database.connect, logging.getLogger('example'))

    def run(self):
        """Runs the check and prints each leg and the summary.

        Returns:
            None: This method returns nothing.
        """
        start = datetime.datetime(2026, 10, 6, tzinfo=INDIA)
        comparisons = self.check.compare(start, start + datetime.timedelta(days=1))
        for comparison in comparisons:
            leg = comparison['leg']
            print(f"{leg['parent_order_id']} leg {leg['leg_id']} {leg['order_type']} {leg['transaction_type']}: crossing {comparison['crossing']}, estimated {comparison['estimated_basis_points']}, actual {comparison['actual_basis_points']}")
        for line in self.check.summary(comparisons):
            print(line)


if __name__ == '__main__':
    CheckingThreeLegsExample().run()
