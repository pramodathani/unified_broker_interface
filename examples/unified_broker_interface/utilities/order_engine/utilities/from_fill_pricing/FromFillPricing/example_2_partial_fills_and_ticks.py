"""Shows an exit before anything has filled, priced from the average of two partial fills, rounded with and without a tick size, and refused when the price would be zero or below.

Before the opening order has filled there is no price, so `opening_fill` and `priced_body` both answer None and nothing is sent. Over two partial fills, 100 at 1,008 and 300 at 1,012.17, the opening fill is their average weighted by quantity, 1,011.1275; a leg placed by some other order in the plan is left out of it. A stop 7.5 below that average is 1,003.6275, which `on_tick` rounds to the nearest 0.05 tick as 1,003.65, and leaves untouched when the tick size is not known. Last, a target 50 below a short opened at 40 would be a price of -10, which cannot be sent, so the pricing answers None. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/from_fill_pricing/FromFillPricing/example_2_partial_fills_and_ticks.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.from_fill_pricing import (
    FromFillPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)

ENTRY_PATH = 'root.first'


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


class PartialFillsAndTicksExample:
    """Prices a stop and a target in the cases around an ordinary fill.

    Attributes:
        stop (FromFillPricing): A stop 7.5 from the fill with its limit 1.5 further on.
        target (FromFillPricing): A target 50 from the fill.
        maker (PieceMaker): Builds the broker orders.
    """

    def __init__(self):
        """Builds the two pricings, opened by the plan's first order.

        Returns:
            None: This method returns nothing.
        """
        self.stop = FromFillPricing(
            decimal.Decimal('7.5'),
            decimal.Decimal('1.5'),
            None,
        )
        self.stop.opened_by = [
            ENTRY_PATH,
        ]
        self.target = FromFillPricing(
            None,
            None,
            decimal.Decimal('50'),
        )
        self.target.opened_by = [
            ENTRY_PATH,
        ]
        self.maker = PieceMaker()

    def run(self):
        """Prints each case.

        Returns:
            None: This method returns nothing.
        """
        waiting = [
            self.maker.piece(1, 400, 'acknowledged', 0, ENTRY_PATH, None, 'BUY'),
        ]
        waiting_context = StandInContext(waiting, decimal.Decimal('0.05'))
        print(f'Nothing filled yet: opening fill {self.stop.opening_fill(waiting_context.parent)}, sent as {self.stop.priced_body(waiting_context, {}, "SELL", {}, {})}')

        partial = [
            self.maker.piece(1, 100, 'filled', 100, ENTRY_PATH, 1008.0, 'BUY'),
            self.maker.piece(2, 300, 'filled', 300, ENTRY_PATH, 1012.17, 'BUY'),
            self.maker.piece(3, 50, 'filled', 50, 'root.then', 900.0, 'SELL'),
        ]
        average = self.stop.opening_fill(StandInParent(partial))
        print(f'Two partial fills, 100 at 1008.0 and 300 at 1012.17: opening fill {average}')
        trigger = average - self.stop.stop_distance
        print(f'on_tick({trigger}) with a 0.05 tick: {self.stop.on_tick(trigger, decimal.Decimal("0.05"))}')
        print(f'on_tick({trigger}) with no tick size: {self.stop.on_tick(trigger, None)}')
        print(f'Stop sent with a 0.05 tick: {self.stop.priced_body(StandInContext(partial, decimal.Decimal("0.05")), {}, "SELL", {}, {})}')
        print(f'Stop sent with no tick size: {self.stop.priced_body(StandInContext(partial, None), {}, "SELL", {}, {})}')

        cheap = [
            self.maker.piece(1, 10, 'filled', 10, ENTRY_PATH, 40.0, 'SELL'),
        ]
        print(f'A target 50 below a short opened at 40.0: {self.target.priced_body(StandInContext(cheap, decimal.Decimal("0.05")), {}, "BUY", {}, {})}')


if __name__ == '__main__':
    PartialFillsAndTicksExample().run()
