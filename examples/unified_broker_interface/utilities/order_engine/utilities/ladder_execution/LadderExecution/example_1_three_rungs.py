"""Spreads a buy of 100 over three rungs from 995 to 1,000.

`LadderExecution.due_pieces` sends every rung at once, the quantity shared by `quantities` as 34, 33 and 33, and `rung_prices` spaces the prices evenly and rounds each down to the tick, the passive side for a buy, so the middle rung of 997.50 stays 997.50. Once the rungs are sent nothing more is due. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/ladder_execution/LadderExecution/example_1_three_rungs.py
"""

import decimal

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


class ThreeRungsExample:
    """Prints a three-rung ladder."""

    def run(self):
        """Prints the rungs.

        Returns:
            None: This method returns nothing.
        """
        execution = LadderExecution(decimal.Decimal('995'), decimal.Decimal('1000'), 3)
        execution.begin(None, {}, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        print(f'Due: {execution.due_pieces(StandInContext(), {}, 100, [], {}, 0.0)} at {execution.rung_prices(StandInContext(), "BUY")}')
        print(f'Once sent, more to send: {execution.will_send_more({}, 100, ["a rung"])}, due {execution.due_pieces(StandInContext(), {}, 100, ["a rung"], {}, 0.0)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    ThreeRungsExample().run()
