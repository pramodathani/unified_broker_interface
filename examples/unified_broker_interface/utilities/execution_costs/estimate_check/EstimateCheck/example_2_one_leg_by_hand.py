"""Takes the estimate check's steps for one leg by hand: read the book, read the daily bars, decide whether the leg crossed, and compare.

`compare` is a short series of steps, and this program calls each one itself against a stand-in database. It also shows that the daily bars are read once per instrument and day, however many legs need them, and that a limit buy priced below the best ask counts as resting. The stand-in database answers the queries from scripted rows, so no PostgreSQL is used.

Notice that the second call for the same day's bars does not read the database again.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/estimate_check/EstimateCheck/example_2_one_leg_by_hand.py
"""

import datetime
import decimal
import logging

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.estimate_check import (
    EstimateCheck,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
SHARE = '2b23b1e8-7d4c-57dd-ab75-99034936574c'


class OneLegByHandExample:
    """Runs each step of the check for one leg.

    Attributes:
        database (StandInExecutionDatabase): The stand-in database.
        check (EstimateCheck): The check.
        decided_at (datetime.datetime): When the leg was decided on.
    """

    def __init__(self):
        """Builds the database and the check.

        Returns:
            None: This method returns nothing.
        """
        self.decided_at = datetime.datetime(2026, 10, 6, 11, 0, 0, tzinfo=INDIA)
        self.database = StandInExecutionDatabase()
        self.database.add_book(SHARE, self.decided_at - datetime.timedelta(milliseconds=300), [('3693.30', 40)], [('3693.40', 25), ('3693.50', 60)])
        for day in range(15):
            bar_time = datetime.datetime(2026, 9, 15, tzinfo=INDIA) + datetime.timedelta(days=day)
            self.database.daily_bars.setdefault(SHARE, []).append((bar_time, decimal.Decimal(3690 + day), 2200000))
        self.check = EstimateCheck(self.database.connect, logging.getLogger('example'))

    def run(self):
        """Runs the steps and prints what each returns.

        Returns:
            None: This method returns nothing.
        """
        with self.database.connect().cursor() as cursor:
            bids, asks = self.check.book_at(cursor, SHARE, self.decided_at)
            print(f'Book: best bid {bids[0]}, asks {asks[:2]}')
            print(f'Book two minutes later: {self.check.book_at(cursor, SHARE, self.decided_at + datetime.timedelta(minutes=2))}')
            liquidity = self.check.liquidity_before(cursor, SHARE, self.decided_at)
            self.check.liquidity_before(cursor, SHARE, self.decided_at)
            print(f'Daily bars: {len(liquidity.closes)} closes, read {self.database.daily_bar_reads} time')
            limit_below = {
                'order_type': 'LIMIT',
                'transaction_type': 'BUY',
                'price': decimal.Decimal('3693.35'),
            }
            limit_through = {
                'order_type': 'LIMIT',
                'transaction_type': 'BUY',
                'price': decimal.Decimal('3693.50'),
            }
            print(f'Limit at 3693.35 crosses: {self.check.is_crossing(limit_below, bids, asks)}; at 3693.50: {self.check.is_crossing(limit_through, bids, asks)}')
            leg = {
                'instrument_id': SHARE,
                'segment': 'nse_equities',
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'price': decimal.Decimal('3693.50'),
                'filled_quantity': 40,
                'decided_at': self.decided_at,
                'decision_mid': decimal.Decimal('3693.35'),
                'half_spread_cost': decimal.Decimal('0.05'),
                'beyond_touch_cost': decimal.Decimal('0.04'),
            }
            comparison = self.check.compare_leg(cursor, leg)
        print(f"Estimated {comparison['estimated_basis_points']} bps, actual {comparison['actual_basis_points']} bps, crossing {comparison['crossing']}")
        print(f"Mean of 0.10, 0.25 and 0.40: {self.check.mean([decimal.Decimal('0.10'), decimal.Decimal('0.25'), decimal.Decimal('0.40')])}")


if __name__ == '__main__':
    OneLegByHandExample().run()
