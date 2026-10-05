"""Shows that a cancelled order and a rejected order both stop the top-ups until the target next grows.

`TopUpExecution.committed` counts only what filled of a finished order, so a hedge of 500 cancelled after 200 filled leaves 300 missing. `will_send_more` is false once the last order was cancelled or rejected, so neither is sent again at once: an `IOC` hedge the exchange cancels would otherwise be followed by another straight away, for ever. The order part sends what is missing when the first plan next fills. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/top_up_execution/TopUpExecution/example_2_cancelled_and_rejected.py
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


class CancelledAndRejectedExample:
    """Prints a top-up after a cancel and after a rejection."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = TopUpExecution()
        maker = PieceMaker()
        cancelled = [
            maker.piece(1, 500, 'cancelled', 200),
        ]
        print(f'After a cancel at 200 of 500: committed {execution.committed(cancelled)}, more to send {execution.will_send_more({}, 300, cancelled)}, due {execution.due_pieces(None, {}, 500, cancelled, {}, 0.0)}')
        rejected = [
            maker.piece(1, 500, 'rejected', 0),
        ]
        print(f'After a rejection: more to send {execution.will_send_more({}, 500, rejected)}, due {execution.due_pieces(None, {}, 500, rejected, {}, 0.0)}')


if __name__ == '__main__':
    CancelledAndRejectedExample().run()
