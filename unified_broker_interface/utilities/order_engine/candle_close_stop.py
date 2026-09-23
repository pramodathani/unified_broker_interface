"""A stop that waits for a candle to close beyond the level before it acts."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.hidden_stop import HiddenStop
from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)

DEFAULT_BAR_MINUTES = 5


class CandleCloseStop(HiddenStop):
    """A hidden stop that fires only when a whole bar has closed past the level.

    The problem it solves is the one every stop has. A level that the market touches for four seconds, on one spike through a thin book, is not the same event as a level the market settles below — but a stop cannot tell the difference, because it only sees the price at the moment it crosses. Waiting for a fifteen-minute candle to close below the level is a way of asking the market to mean it.

    That is bought with two real costs and they should be stated plainly. The stop is **late**: on a genuine breakdown it exits at the close of the bar rather than at the level, which on a fast move is a long way below. And it is **quiet in between**: between the level being crossed and the bar closing, nothing is protecting the position at all.

    The second cost is what `backstop_price` is for, inherited from the hidden stop this subclasses: a real stop-loss limit resting at the exchange, further away, catching the move this one deliberately sits through.

    It is otherwise the hidden stop in every respect — the same exit, the same cancel-the-backstop-first ordering, the same everything — and differs only in what it looks at. Instead of the current bid or offer, it looks at the close of the bar that just ended, so it answers the question at most once per bar and does nothing at all on the ticks in between.

    The bars are built from the engine's own price ticks from the moment the order was placed, which means an order placed at eleven o'clock has no bar to judge until the first one ends. During that time the backstop is the only protection, which is another reason to set one.

    Attributes:
        tick_moment (float): The Unix time of the tick being handled, so that the candle builder and the level check work from the same moment.
    """

    SYNTHETIC_TYPE = 'candle_close_stop'
    tick_moment = 0.0
    ARMED_MESSAGE = 'a candle closes past the level'

    def read_bar_minutes(self):
        """How long one candle lasts.

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

    def builder(self):
        """The bar builder over this parent's stored candles.

        Returns:
            BarBuilder: The builder.
        """
        self.parent.parameters = dict(self.parent.parameters)
        return BarBuilder(
            self.parent.parameters,
            self.read_bar_minutes() * 60,
        )

    def watched_price(self, view):
        """The close of the candle that just ended, or None on every other tick.

        Returning None on the ticks in between is what makes the stop ask its question once per bar. The price trigger it inherits from treats a missing price as "nothing to decide yet", which is exactly right here.

        Args:
            view (MarketView): The instrument's quote.

        Returns:
            decimal.Decimal | None: The closed bar's close, or None when no bar closed on this tick.
        """
        price = view.last()
        if price is None:
            return None
        closed = self.builder().add(price, self.tick_moment)
        self.save()
        if closed is None:
            return None
        return closed['close']

    def on_price_tick(self, quotes, now):
        """Feeds the tick into the candle being built, and acts when one closes past the level.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the stop fired on this tick.
        """
        self.tick_moment = now
        return super().on_price_tick(quotes, now)
