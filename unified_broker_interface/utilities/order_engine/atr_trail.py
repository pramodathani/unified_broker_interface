"""A trailing stop whose distance is how much the instrument has been moving."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)
from unified_broker_interface.utilities.order_engine.utilities.trailing import (
    TrailingOrder,
)

DEFAULT_BAR_MINUTES = 5
DEFAULT_PERIODS = 14
DEFAULT_MULTIPLE = 2.0


class AtrTrail(TrailingOrder):
    """A trailing stop that sits a multiple of the recent average range behind the market.

    A fixed trail has one number and the market has many. Ten rupees behind is generous on a quiet morning and is hit by ordinary noise in the afternoon; the same ten rupees is far too tight the day the result comes out. A stop that measures how much the instrument has actually been moving lately, and sits a multiple of that behind, adjusts to both without anybody watching.

    The measure is the average true range, which is the usual one. A bar's true range is the greater of its own high-to-low span and the distance from the previous close, so a gap counts as movement rather than being ignored — which matters in India, where an overnight gap is often the whole of a day's move.

    **The bars come from the engine's own price ticks from the moment this order was placed**, not from the price history tables, so the average is not available at once. `periods` bars have to close first: fourteen five-minute bars is seventy minutes. Until then the stop trails at `trail_points`, which is required for exactly this reason, and the switch happens quietly the first time there is enough history.

    That is a real limitation rather than a detail. An order placed at ten past three will never reach fourteen five-minute bars before the close, and will behave as a fixed trail for its whole life. Somebody who wants the average from the first tick should be using shorter bars or placing the order earlier.

    Everything else it inherits from the trailing stop: the ratchet that never moves backwards, the stop resting at the broker so that it survives an outage, and `step_ticks` so that a stop is not moved a paisa at a time.
    """

    SYNTHETIC_TYPE = 'atr_trail'
    ARMED_STATE = 'protecting'
    tick_moment = 0.0

    def leg_side(self, transaction_type):
        """The side that closes the position, which is the side the stop trades.

        Args:
            transaction_type (str): The side that opened the position.

        Returns:
            str: BUY to protect a short, SELL to protect a long.
        """
        return 'SELL' if transaction_type == 'BUY' else 'BUY'

    def read_bar_minutes(self):
        """How long one bar lasts.

        Returns:
            float: The length in minutes.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number above zero.
        """
        value = self.parent.parameters.get(
            'bar_minutes',
            DEFAULT_BAR_MINUTES,
        )
        try:
            minutes = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'bar_minutes must be a number of minutes, not {value!r}',
                400,
            )
        if minutes <= 0:
            raise RefusedRequestError.refusal(
                f'bar_minutes must be above zero, not {minutes}',
                400,
            )
        return minutes

    def read_periods(self):
        """How many bars the average covers.

        Returns:
            int: The count.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number above one.
        """
        value = self.parent.parameters.get('periods', DEFAULT_PERIODS)
        try:
            periods = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'periods must be a whole number of bars, not {value!r}',
                400,
            )
        if periods < 2:
            raise RefusedRequestError.refusal(
                f'periods must be at least two bars, not {periods}',
                400,
            )
        return periods

    def read_multiple(self):
        """How many average ranges the stop sits behind the market.

        Returns:
            decimal.Decimal: The multiple.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number above zero.
        """
        return self.positive(
            self.parent.parameters.get('atr_multiple', DEFAULT_MULTIPLE),
            'atr_multiple',
        )

    def builder(self):
        """The bar builder over this parent's stored bars.

        Returns:
            BarBuilder: The builder.
        """
        self.parent.parameters = dict(self.parent.parameters)
        return BarBuilder(
            self.parent.parameters,
            self.read_bar_minutes() * 60,
        )

    def read_trail(self, reference):
        """How far the trigger sits from the watermark, from the average range once there is one.

        Args:
            reference (decimal.Decimal): The watermark, which the fixed fallback ignores.

        Returns:
            decimal.Decimal: The distance, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when `trail_points` is missing, since it is the fallback until there are enough bars.
        """
        if self.parent.parameters.get('trail_points') is None:
            raise RefusedRequestError.refusal(
                'an average-range trail needs trail_points as well: the bars '
                'it measures are built from this order onwards, so there is '
                'nothing to average until enough of them have closed',
                400,
            )
        average = self.builder().average_true_range(self.read_periods())
        if average is None:
            return self.positive(
                self.parent.parameters.get('trail_points'),
                'trail_points',
            )
        return average * self.read_multiple()

    def on_price_tick(self, quotes, now):
        """Adds the tick to the bar being built, then trails as a trailing stop does.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the stop was moved.
        """
        self.tick_moment = now
        view = self.view(quotes)
        price = view.last()
        if price is not None:
            self.builder().add(price, now)
            self.save()
        return super().on_price_tick(quotes, now)
