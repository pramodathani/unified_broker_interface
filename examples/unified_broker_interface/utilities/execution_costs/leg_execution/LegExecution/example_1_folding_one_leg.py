"""Folds one leg's rows from the engine's event log into what is needed to measure it.

The order engine writes a `leg_requested` row before sending a leg, a `leg_answered` row when the broker answers, and a `leg_update` row whenever the broker reports a change. An update carries only what changed, so a fill's quantity and price can arrive on different rows. This program feeds in five such rows by hand, so it reads no database.

Notice that the second update changes only the quantity and the third only the price, and the leg ends up with both.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/leg_execution/LegExecution/example_1_folding_one_leg.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class FoldingOneLegExample:
    """Applies a leg's rows one by one and prints what the leg knows after each.

    Attributes:
        leg (LegExecution): The leg.
        rows (list): The rows, as dicts by column name.
    """

    def __init__(self):
        """Builds the leg and its rows.

        Returns:
            None: This method returns nothing.
        """
        decided_at = datetime.datetime(2026, 10, 6, 10, 15, 0, tzinfo=INDIA)
        self.leg = LegExecution('7f9c0a52-0c1e-4f7b-9d4a-3b2e1c0d9e8f', '1', decided_at)
        self.rows = [
            {
                'event': 'leg_requested',
                'time': datetime.datetime(2026, 10, 6, 10, 15, 0, 200000, tzinfo=INDIA),
                'synthetic_type': 'simple',
                'leg_role': 'entry',
                'broker': 'flattrade',
                'instrument_id': 'b51c2f7e-5a0d-4c43-9e11-0f6a2d7c8b19',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 65,
            },
            {
                'event': 'leg_answered',
                'time': datetime.datetime(2026, 10, 6, 10, 15, 0, 300000, tzinfo=INDIA),
                'outcome': 'accepted',
            },
            {
                'event': 'leg_update',
                'filled_quantity': 30,
                'average_price': decimal.Decimal('238.80'),
            },
            {
                'event': 'leg_update',
                'filled_quantity': 65,
            },
            {
                'event': 'leg_update',
                'average_price': decimal.Decimal('238.90'),
            },
        ]

    def run(self):
        """Applies each row and prints the leg's state.

        Returns:
            None: This method returns nothing.
        """
        for row in self.rows:
            self.leg.apply(row)
            print(f'after {row["event"]}: outcome {self.leg.outcome}, filled {self.leg.filled_quantity} at {self.leg.average_price}, measurable {self.leg.is_filled()}')
        print(f'Sent at {self.leg.sent_at.time()}, answered at {self.leg.answered_at.time()}, side {self.leg.side()}')


if __name__ == '__main__':
    FoldingOneLegExample().run()
