"""Walks a hedge whose target grows from 500 to 1,000 as its entry fills, sending a new order for each missing part.

`TopUpExecution.due_pieces` sends one order for the target less what is resting or filled, and never asks to resize a resting order, so every hedge keeps its price and place in the queue. `committed` is what the orders sent so far account for. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/top_up_execution/TopUpExecution/example_1_a_new_order_for_each_lot.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.top_up_execution import (
    TopUpExecution,
)


class PieceMaker:
    """Builds broker orders as the engine records them."""

    def piece(self, number, quantity, state, filled, role='root', price=None, side='BUY'):
        """One broker order.

        Args:
            number (int): Its number, for its id.
            quantity (int): Its quantity.
            state (str): Its state, such as `acknowledged` or `filled`.
            filled (int): How much of it has filled.
            role (str): Its role, the path of the order that placed it.
            price (float | None): The average price it filled at, or None.
            side (str): BUY or SELL.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg(f'parent-1:{number}', role)
        leg.quantity = quantity
        leg.state = state
        leg.filled_quantity = filled
        leg.average_price = price
        leg.transaction_type = side
        return leg


class ANewOrderForEachLotExample:
    """Walks a growing target."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        execution = TopUpExecution()
        maker = PieceMaker()
        execution.begin(None, {}, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        pieces = []
        for target in (0, 500, 500, 1000):
            due = execution.due_pieces(None, {}, target, pieces, {}, 0.0)
            print(f'Target {target}: committed {execution.committed(pieces)}, due {due}')
            for quantity in due:
                pieces.append(maker.piece(len(pieces) + 1, quantity, 'acknowledged', 0))
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    ANewOrderForEachLotExample().run()
