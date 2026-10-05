"""Shows a liquidity-seeking sell after a strike that partly filled, and after one the broker rejected.

A strike that only partly fills rests at its limit, so `BookDepthExecution.committed` counts the whole of a resting strike and the next strike is only for what is neither traded nor resting. A strike the broker rejects stops the order, which `last_was_rejected` and `will_send_more` both say. A sell reads the bids rather than the offers. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/book_depth_execution/BookDepthExecution/example_2_partial_strikes_and_a_rejection.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.book_depth_execution import (
    BookDepthExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInPlanOrder:
    """Stands in for the plan order, which reads a quote into a market view."""

    def view(self, quotes):
        """The market, as the instrument's quote shows it, with a tick of five paise.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(INSTRUMENT_ID), decimal.Decimal('0.05'))

    def lot_size(self):
        """The lot every slice must be a whole number of, which for a share is one.

        Returns:
            int: One.
        """
        return 1


class PieceMaker:
    """Builds broker orders as the engine records them, in a chosen state."""

    def piece(self, number, quantity, state, filled):
        """One broker order.

        Args:
            number (int): Its number, for its id.
            quantity (int): Its quantity.
            state (str): Its state, such as `acknowledged` or `rejected`.
            filled (int): How much of it has filled.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg(f'parent-1:{number}', 'root')
        leg.quantity = quantity
        leg.state = state
        leg.filled_quantity = filled
        return leg


class PartialStrikesAndARejectionExample:
    """Prints a liquidity-seeking sell's answers after earlier strikes."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = BookDepthExecution(decimal.Decimal('999.90'), 5)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        quotes = {
            INSTRUMENT_ID: {
                'depth': {
                    'buy': [
                        {
                            'price': 1000.00,
                            'quantity': 30,
                        },
                        {
                            'price': 999.85,
                            'quantity': 100,
                        },
                    ],
                    'sell': [],
                },
            },
        }
        print(f'Bids no worse than 999.90: {execution.reachable_quantity(plan_order.view(quotes), "SELL")}')
        resting = [
            maker.piece(1, 30, 'acknowledged', 12),
        ]
        print(f'With a strike of 30 resting, 12 filled: committed {execution.committed(resting)}, due {execution.due_pieces(plan_order, {}, 50, resting, quotes, 0.0, sending_side="SELL")}')
        rejected = [
            maker.piece(1, 30, 'rejected', 0),
        ]
        print(f'After a rejected strike: last was rejected {execution.last_was_rejected(rejected)}, more to send {execution.will_send_more({}, 50, rejected)}, due {execution.due_pieces(plan_order, {}, 50, rejected, quotes, 0.0, sending_side="SELL")}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    PartialStrikesAndARejectionExample().run()
