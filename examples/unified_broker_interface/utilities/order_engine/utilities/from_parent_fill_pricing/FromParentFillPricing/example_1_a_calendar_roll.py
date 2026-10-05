"""Prices the sold future of a spread bought for a net of 20, once the stock leg filled 500 at an average of 1,002.

`FromParentFillPricing.first_fill` reads the first leg's average fill and side from the legs whose role is `first_path`, which the plan reader sets to the Then join's first order. `second_price` is the net less the signed fill, signed again by the second leg's side: a sell at 982 makes 1,002 paid less 982 received a net of 20. When the stock leg then fills 500 more at 1,004, its average is 1,003, so the future should average 983; `sent_before` counts the 500 already resting at 982, and `next_price` sends the new 500 at 984, so the whole spread still nets 20. Prices are rounded to the future's tick of 0.10 in the caller's favour. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/from_parent_fill_pricing/FromParentFillPricing/example_1_a_calendar_roll.py
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
    """Stands in for the second leg's view of the plan order, trading a future whose tick is 0.10.

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

    def tick_size(self):
        """The second leg's tick size.

        Returns:
            decimal.Decimal: 0.10.
        """
        return decimal.Decimal('0.10')


class ACalendarRollExample:
    """Prices the second leg of a spread."""

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        pricing = FromParentFillPricing(decimal.Decimal('20'))
        pricing.first_path = 'root.first'
        pricing.own_path = 'root.each_fill'
        maker = PieceMaker()
        legs = [
            maker.piece(1, 1000, 'acknowledged', 500, 'root.first', 1002.0, 'BUY'),
        ]
        context = StandInContext(legs)
        print(f'Reads quotes: {pricing.needs_prices()}, moves: {pricing.moves()}')
        print(f'First fill: {pricing.first_fill(context.parent)}')
        print(f'Sent as: {pricing.priced_body(context, {"quantity": 500}, "SELL", {}, {})}')
        second = maker.piece(2, 500, 'acknowledged', 0, 'root.each_fill', None, 'SELL')
        second.price = 982.0
        legs.append(second)
        legs[0].filled_quantity = 1000
        legs[0].average_price = 1003.0
        print(f'Sent before: {pricing.sent_before(context.parent)}')
        print(f'After 500 more at 1,004, the next 500 is sent as: {pricing.priced_body(context, {"quantity": 500}, "SELL", {}, {})}')
        print(f'As a dry run shows it: {pricing.described()}')


if __name__ == '__main__':
    ACalendarRollExample().run()
