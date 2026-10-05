"""The trigger condition that holds when a whole bar closes past a level."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)


class CandleClosesCondition:
    """A plan order's trigger condition that holds when a bar built from the engine's own ticks closes past `level`, rather than when any tick touches it.

    It keeps the rules of today's candle close stop. A spike through a level on a thin book is not the market settling past it, so the condition answers at most once per bar, at its close, and does nothing on the ticks between. The bars are `bar_minutes` long, built from the last traded price, aligned to the clock, and kept in the condition's memory. The bar the order is placed in counts as a bar, though it holds only the ticks since then, so the first answer comes at the next clock boundary, which can be seconds away. With no direction, a long, opened with a BUY, waits for a close at or below the level, and a short for one at or above it.

    Attributes:
        level (decimal.Decimal): The level a close must reach.
        direction (str | None): `at_or_above` or `at_or_below`, or None to follow the opening side.
        bar_minutes (float): How long one bar lasts.
    """

    def __init__(self, level, direction, bar_minutes):
        """Builds the condition from settings the plan reader has already checked.

        Args:
            level (decimal.Decimal): The level.
            direction (str | None): The direction, or None.
            bar_minutes (float): How long one bar lasts.

        Returns:
            None: This method returns nothing.
        """
        self.level = level
        self.direction = direction
        self.bar_minutes = bar_minutes

    def needs_prices(self):
        """Whether this condition reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def instruments(self):
        """The instruments this condition watches beside the order's own, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def prepare(self, plan_order, memory):
        """Readies the condition, which needs nothing until the first tick.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory

    def effective_direction(self, opening_side):
        """Which way a close has to land for this condition to hold.

        Args:
            opening_side (str): BUY or SELL, the side that opened the position.

        Returns:
            str: `at_or_above` or `at_or_below`.
        """
        if self.direction is not None:
            return self.direction
        if opening_side == 'BUY':
            return 'at_or_below'
        return 'at_or_above'

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the bar that has just closed closed past the level.

        A quote marked stale adds nothing to the bar, as if no tick had come. It also keeps `closing_past`, whether the bar in progress would hold if it closed at this price. The plan records the memory with an event when that changes, so an engine restarted late in a bar still knows which side of the level the bar was closing on, without an event on every tick.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which reads quotes into prices.
            memory (dict): The condition's memory, holding the bars, changed in place.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.
            opening_side (str): BUY or SELL, the side that opened the position.
            sending_side (str): Unused.

        Returns:
            bool: True when a bar closed past the level on this tick.
        """
        del sending_side
        view = plan_order.view(quotes)
        if view.is_stale():
            return False
        price = view.last()
        if price is None:
            return False
        if 'bars' not in memory:
            memory['bars'] = {}
        direction = self.effective_direction(opening_side)
        closed = BarBuilder(memory['bars'], self.bar_minutes * 60).add(price, now)
        memory['closing_past'] = self.is_past(price, direction)
        if closed is None:
            return False
        return self.is_past(decimal.Decimal(str(closed['close'])), direction)

    def is_past(self, price, direction):
        """Whether a price is at or past the level, the way a close has to be.

        Args:
            price (decimal.Decimal): The price.
            direction (str): `at_or_above` or `at_or_below`.

        Returns:
            bool: True when it is.
        """
        if direction == 'at_or_above':
            return price >= self.level
        return price <= self.level

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'candle_closes': {
                'level': str(self.level),
                'direction': self.direction or 'from the opening side',
                'bar_minutes': self.bar_minutes,
            },
        }
