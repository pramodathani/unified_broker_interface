"""Shows a sell ladder whose prices do not fall on the tick, and a ladder with fewer units than rungs.

A sell rounds each rung up, its passive side, so a range of 1,000.00 to 1,000.12 over four rungs rests at 1,000.00, 1,000.05, 1,000.10 and 1,000.15 rather than crossing. A quantity smaller than the number of rungs is refused. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/ladder_execution/LadderExecution/example_2_a_sell_and_too_few.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.ladder_execution import (
    LadderExecution,
)


class StandInContext:
    """Stands in for the order's view of the plan order, which knows the tick size."""

    def tick_size(self):
        """The instrument's tick size, five paise.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')

    def lot_size(self):
        """The lot every rung must be a whole number of, which for a share is one.

        Returns:
            int: One.
        """
        return 1


class ASellAndTooFewExample:
    """Prints a sell ladder and a refusal."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = LadderExecution(decimal.Decimal('1000.00'), decimal.Decimal('1000.12'), 4)
        print(f'Sell rungs: {execution.rung_prices(StandInContext(), "SELL")}, quantities for 10: {execution.quantities(10)}')
        try:
            execution.due_pieces(StandInContext(), {}, 3, [], {}, 0.0)
        except RefusedRequestError as refusal:
            print(f'Three units over four rungs: {refusal.status} {refusal.body["error"]}')


if __name__ == '__main__':
    ASellAndTooFewExample().run()
