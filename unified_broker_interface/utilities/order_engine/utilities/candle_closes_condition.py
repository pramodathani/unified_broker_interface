"""The trigger condition that holds when a whole bar closes past a level."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)


class CandleClosesCondition:
    """A plan order's trigger condition that holds when a bar built from the engine's own ticks closes past `level`, rather than when any tick touches it.

    It keeps the rules of today's candle close stop. A spike through a level on a thin book is not the market settling past it, so the condition answers at most once per bar, at its close, and does nothing on the ticks between. The bars are `bar_minutes` long, built from the last traded price, aligned to the clock, and kept in the condition's memory, so nothing is known until the first bar after the order rests has closed. With no direction, a long, opened with a BUY, waits for a close at or below the level, and a short for one at or above it.

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
        price = plan_order.view(quotes).last()
        if price is None:
            return False
        if 'bars' not in memory:
            memory['bars'] = {}
        closed = BarBuilder(memory['bars'], self.bar_minutes * 60).add(price, now)
        if closed is None:
            return False
        close = decimal.Decimal(str(closed['close']))
        if self.effective_direction(opening_side) == 'at_or_above':
            return close >= self.level
        return close <= self.level

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
