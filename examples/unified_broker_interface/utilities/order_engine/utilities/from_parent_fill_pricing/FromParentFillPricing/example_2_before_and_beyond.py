"""Shows a second leg before the first has filled, averaged over two fills, and at a net that would need a price below zero.

Before anything fills there is no price, so the order waits. Over two fills the average is weighted by quantity. A net that would make the second leg's price zero or below cannot be sent. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/from_parent_fill_pricing/FromParentFillPricing/example_2_before_and_beyond.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.from_parent_fill_pricing import (
    FromParentFillPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
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


class StandInParent:
    """Stands in for the plan order's parent.

    Attributes:
        legs (list): The broker orders placed.
    """

    def __init__(self, legs):
        """Builds the parent.

        Args:
            legs (list): The broker orders placed.

        Returns:
            None: This method returns nothing.
        """
        self.legs = legs


class StandInContext:
    """Stands in for the second leg's view of the plan order.

    Attributes:
        parent (StandInParent): The parent.
    """

    def __init__(self, legs):
        """Builds the context.

        Args:
            legs (list): The broker orders placed.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(legs)


class BeforeAndBeyondExample:
    """Prints a second leg's price in three cases."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        pricing = FromParentFillPricing(decimal.Decimal('-5'))
        pricing.first_path = 'root.first'
        maker = PieceMaker()
        print(f'Nothing filled yet: {pricing.priced_body(StandInContext([]), {}, "BUY", {}, {})}')
        legs = [
            maker.piece(1, 100, 'filled', 100, 'root.first', 50.0, 'SELL'),
            maker.piece(2, 300, 'filled', 300, 'root.first', 54.0, 'SELL'),
        ]
        print(f'Average of two sells: {pricing.first_fill(StandInParent(legs))}, so a buy at {pricing.second_price(decimal.Decimal("53"), "SELL", "BUY")}')
        print(f'A net needing a price below zero: {pricing.priced_body(StandInContext(legs), {}, "SELL", {}, {})}')


if __name__ == '__main__':
    BeforeAndBeyondExample().run()
