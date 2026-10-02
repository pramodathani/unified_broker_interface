"""Prices a stop and a target from one set of distances, first for a long opened at 1,010 and then for a short opened at 990.

Under a two-sided breakout the exits are `from_fill` pricings, because nobody knows in advance which way the range will break. `FromFillPricing` reads the opening fill from the legs whose role is in `opened_by`, which the plan reader sets to the paths of the Then join's first orders: here the buy stop above the range and the sell stop below it. Only the side that broke has filled, so the exit follows that side.

The stop is 10 from the fill with its limit 2 further on, and the target is 20 from it. When the buy side opens a long at 1,010, the exits are sells: a stop triggering at 1,000 with its limit at 998, and a target at 1,030. When the sell side opens a short at 990 instead, the same distances give buys: a stop triggering at 1,000 with its limit at 1,002, above the fill, and a target at 970, below it. `is_stop` tells the two pricings apart, `needs_prices` and `moves` show that neither reads quotes nor moves a resting order, and `described` is how a dry run shows each one. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/from_fill_pricing/FromFillPricing/example_1_either_side_of_a_break.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.from_fill_pricing import (
    FromFillPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)

BUY_SIDE_PATH = 'root.first.children.0'
SELL_SIDE_PATH = 'root.first.children.1'


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
    """Stands in for the exit's view of the plan order.

    Attributes:
        parent (StandInParent): The parent.
        known_tick_size (decimal.Decimal | None): The instrument's tick size, or None when it is not known.
    """

    def __init__(self, legs, known_tick_size):
        """Builds the context.

        Args:
            legs (list): The broker orders placed.
            known_tick_size (decimal.Decimal | None): The instrument's tick size, or None.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent(legs)
        self.known_tick_size = known_tick_size

    def tick_size(self):
        """The instrument's tick size.

        Returns:
            decimal.Decimal | None: The tick size, or None when it is not known.
        """
        return self.known_tick_size


class EitherSideOfABreakExample:
    """Prices the same stop and target for a long and for a short.

    Attributes:
        stop (FromFillPricing): The stop's pricing, 10 from the fill with its limit 2 further on.
        target (FromFillPricing): The target's pricing, 20 from the fill.
        maker (PieceMaker): Builds the broker orders.
    """

    def __init__(self):
        """Builds the two pricings, opened by either side of the range.

        Returns:
            None: This method returns nothing.
        """
        self.stop = FromFillPricing(
            decimal.Decimal('10'),
            decimal.Decimal('2'),
            None,
        )
        self.target = FromFillPricing(
            None,
            None,
            decimal.Decimal('20'),
        )
        opened_by = [
            BUY_SIDE_PATH,
            SELL_SIDE_PATH,
        ]
        self.stop.opened_by = opened_by
        self.target.opened_by = opened_by
        self.maker = PieceMaker()

    def show(self, heading, legs, sending_side):
        """Prints the stop and the target sent on one side, for the legs given.

        Args:
            heading (str): What the legs show.
            legs (list): The broker orders placed.
            sending_side (str): BUY or SELL, the side the exits are sent on.

        Returns:
            None: This method returns nothing.
        """
        context = StandInContext(legs, decimal.Decimal('0.05'))
        print(f'{heading}: opening fill {self.stop.opening_fill(context.parent)}')
        print(f'  stop sent as:   {self.stop.priced_body(context, {"transaction_type": sending_side, "quantity": 20}, sending_side, {}, {})}')
        print(f'  target sent as: {self.target.priced_body(context, {"transaction_type": sending_side, "quantity": 20, "trigger_price": None}, sending_side, {}, {})}')

    def run(self):
        """Prints each pricing's answers.

        Returns:
            None: This method returns nothing.
        """
        print(f'Stop: is_stop {self.stop.is_stop()}, reads quotes {self.stop.needs_prices()}, moves {self.stop.moves()}')
        print(f'Target: is_stop {self.target.is_stop()}, reads quotes {self.target.needs_prices()}, moves {self.target.moves()}')
        print(f'Opened by: {self.stop.opened_by}')
        upside = [
            self.maker.piece(1, 20, 'filled', 20, BUY_SIDE_PATH, 1010.0, 'BUY'),
            self.maker.piece(2, 20, 'cancelled', 0, SELL_SIDE_PATH, None, 'SELL'),
        ]
        self.show('The buy side broke, a long', upside, 'SELL')
        downside = [
            self.maker.piece(1, 20, 'cancelled', 0, BUY_SIDE_PATH, None, 'BUY'),
            self.maker.piece(2, 20, 'filled', 20, SELL_SIDE_PATH, 990.0, 'SELL'),
        ]
        self.show('The sell side broke, a short', downside, 'BUY')
        print(f'As a dry run shows the stop: {self.stop.described()}')
        print(f'As a dry run shows the target: {self.target.described()}')


if __name__ == '__main__':
    EitherSideOfABreakExample().run()
