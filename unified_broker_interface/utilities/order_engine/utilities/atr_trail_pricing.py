"""The pricing that trails a resting stop a multiple of the recent average range behind the market."""

from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)
from unified_broker_interface.utilities.order_engine.utilities.trail_pricing import (
    TrailPricing,
)


class AtrTrailPricing:
    """A plan order's trailing stop whose distance is `multiple` times the average true range of the bars built since it rested.

    It keeps the rules of today's average-range trail. The bars are built from the engine's own price ticks, `bar_minutes` long, into the pricing's memory, so there is nothing to average until `periods` of them have closed; until then the stop trails `points` behind, which is why `points` is required. Everything else is an ordinary `trail`: a native stop-limit that follows the best price seen and never moves back, by at least `step_ticks`.

    Attributes:
        points (decimal.Decimal): The distance until enough bars have closed.
        limit_offset (decimal.Decimal): How far past the trigger the limit sits.
        step_ticks (int): The smallest move worth sending, in ticks.
        bar_minutes (float): How long one bar lasts.
        periods (int): How many closed bars the average needs.
        multiple (decimal.Decimal): How many average ranges behind the stop sits.
    """

    def __init__(self, points, limit_offset, step_ticks, bar_minutes, periods, multiple):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            points (decimal.Decimal): The distance until enough bars have closed.
            limit_offset (decimal.Decimal): How far past the trigger the limit sits.
            step_ticks (int): The smallest move worth sending.
            bar_minutes (float): How long one bar lasts.
            periods (int): How many closed bars the average needs.
            multiple (decimal.Decimal): How many average ranges behind the stop sits.

        Returns:
            None: This method returns nothing.
        """
        self.points = points
        self.limit_offset = limit_offset
        self.step_ticks = step_ticks
        self.bar_minutes = bar_minutes
        self.periods = periods
        self.multiple = multiple

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does.

        Returns:
            bool: True.
        """
        return True

    def bars(self, memory):
        """The builder over the bars kept in the pricing's memory.

        Args:
            memory (dict): The pricing's memory, given a `bars` dictionary when it has none.

        Returns:
            BarBuilder: The builder.
        """
        if 'bars' not in memory:
            memory['bars'] = {}
        return BarBuilder(memory['bars'], self.bar_minutes * 60)

    def distance(self, memory):
        """How far behind the best price the stop sits now.

        Args:
            memory (dict): The pricing's memory, holding the bars.

        Returns:
            decimal.Decimal: The average range times the multiple, or `points` until enough bars have closed.
        """
        average = self.bars(memory).average_true_range(self.periods)
        if average is None:
            return self.points
        return average * self.multiple

    def trail(self, distance):
        """An ordinary trail at a distance, which does the rest of the work.

        Args:
            distance (decimal.Decimal): The distance in price.

        Returns:
            TrailPricing: The trail.
        """
        return TrailPricing(distance, None, self.limit_offset, self.step_ticks)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a stop-limit `points` behind the last price, since no bars have closed yet.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the stop trades.
            quotes (dict): The quotes, by instrument id.
            memory (dict): The pricing's memory, given `best`.

        Returns:
            dict | None: The body, or None when there is no last price to start from.
        """
        return self.trail(self.distance(memory)).priced_body(plan_order, body, sending_side, quotes, memory)

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """Adds this tick's price to the bars, then trails at the distance they give.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The pricing's memory, holding the bars and `best`.
            leg (OrderLeg): The resting stop.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            tuple | None: The new limit and trigger (decimal.Decimal) and a reason (str), or None.
        """
        price = plan_order.view(quotes).last()
        if price is not None:
            self.bars(memory).add(price, now)
        return self.trail(self.distance(memory)).moved_prices(plan_order, memory, leg, quotes, now)

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'trail': {
                'points': str(self.points),
                'limit_offset': str(self.limit_offset),
                'step_ticks': self.step_ticks,
                'atr': {
                    'bar_minutes': self.bar_minutes,
                    'periods': self.periods,
                    'multiple': str(self.multiple),
                },
            },
        }
