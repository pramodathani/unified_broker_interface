"""Splits the cost of a NIFTY option buy that filled at 238.90 when the mid-price had been 238.25 at the decision.

The engine took the order when the book was 238.00 bid and 238.50 ask. By the time it sent the leg the book had moved up a tick, and by the time the broker answered it had moved up another. The fill came in 0.20 above that moment's ask, because the order took more than the best level held. This program builds the leg and the three quotes by hand, so it reads no database.

Notice that the four parts add up to the total of 0.65 per unit, which is 27.28 basis points or 42.25 rupees on 65 units, and that only the latency part depends on the broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/execution_cost/ExecutionCost/example_1_a_buy_that_walked_the_book.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.execution_cost import (
    ExecutionCost,
)
from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)
from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class BuyThatWalkedTheBookExample:
    """Prints every part of one buy's cost.

    Attributes:
        cost (ExecutionCost): The cost.
    """

    def __init__(self):
        """Builds the leg, its quotes and its cost.

        Returns:
            None: This method returns nothing.
        """
        decided_at = datetime.datetime(2026, 10, 6, 10, 15, 0, tzinfo=INDIA)
        leg = LegExecution('7f9c0a52-0c1e-4f7b-9d4a-3b2e1c0d9e8f', '1', decided_at)
        leg.transaction_type = 'BUY'
        leg.filled_quantity = 65
        leg.average_price = decimal.Decimal('238.90')
        at_decision = QuoteMoment(decided_at, decimal.Decimal('238.00'), decimal.Decimal('238.50'))
        at_send = QuoteMoment(decided_at, decimal.Decimal('238.10'), decimal.Decimal('238.60'))
        at_answer = QuoteMoment(decided_at, decimal.Decimal('238.20'), decimal.Decimal('238.70'))
        self.cost = ExecutionCost(leg, at_decision, at_send, at_answer, 'nse_equity_index_options', True)

    def run(self):
        """Prints the parts, the total and the table row's cost columns.

        Returns:
            None: This method returns nothing.
        """
        print(f'Delay:             {self.cost.delay()}')
        print(f'Latency:           {self.cost.latency()}')
        print(f'Half spread:       {self.cost.half_spread()}')
        print(f'Beyond the touch:  {self.cost.beyond_touch()}')
        print(f'Total per unit:    {self.cost.total()}')
        print(f'Total, basis points: {self.cost.basis_points(self.cost.total())}')
        print(f'Total, rupees:     {self.cost.total_rupees()}')
        row = self.cost.row()
        print(f"Row: decision mid {row['decision_mid']}, latency {row['latency_cost_basis_points']} bps, total {row['total_cost']}")


if __name__ == '__main__':
    BuyThatWalkedTheBookExample().run()
