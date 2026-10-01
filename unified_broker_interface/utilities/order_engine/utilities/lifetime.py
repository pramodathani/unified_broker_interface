"""When a plan order stops working, and what is done with it then."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)

APPLIES_TO = (
    'waiting',
    'working',
    'both',
)
ON_END = (
    'cancel',
    'marketable',
    'close_filled',
)
SECONDS_IN_A_DAY = 86400
WAITING_STATES = (
    'pending',
    'waiting',
)


class Lifetime:
    """A plan order's lifetime: a moment it ends at, which part of its life that bounds, and what is done when it ends.

    The end is `at_time`, a time of day on the instrument's next trading day, `after_minutes`, counted from when the plan is placed, as today's time stop counts them, or `after_days`, counted the same way, as today's gtt counts its `valid_days`; a plan with an end in days outlives the trading day. `applies_to` says whether the end bounds the time the order waits for its trigger, the time it works after it is sent, or both. An order still waiting when it ends is simply done. An order working when it ends has its resting orders cancelled (`cancel`), moved past the other side's touch so they fill (`marketable`, today's good-till-time `market`), or cancelled and then what filled closed at market (`close_filled`, today's time stop).

    Attributes:
        at_time (str | None): The time of day it ends at, or None.
        after_minutes (float | None): The minutes after placing it ends, or None.
        applies_to (str): `waiting`, `working` or `both`.
        on_end (str): `cancel`, `marketable` or `close_filled`.
        after_days (int | None): The days after placing it ends, or None.
    """

    def __init__(self, at_time, after_minutes, applies_to, on_end, after_days=None):
        """Builds the lifetime from settings the plan reader has already checked.

        Args:
            at_time (str | None): The time of day, or None.
            after_minutes (float | None): The minutes, or None.
            applies_to (str): `waiting`, `working` or `both`.
            on_end (str): `cancel`, `marketable` or `close_filled`.
            after_days (int | None): The days, or None.

        Returns:
            None: This method returns nothing.
        """
        self.at_time = at_time
        self.after_minutes = after_minutes
        self.applies_to = applies_to
        self.on_end = on_end
        self.after_days = after_days

    def ends_at(self, plan_order, now=None):
        """The Unix time the order ends at, worked out when the plan is placed.

        Args:
            plan_order (PlanOrder): The plan order, which knows its instrument's segment.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            float: The moment.

        Raises:
            RefusedRequestError: With HTTP 400 when the time has already passed today, or minutes are given on a day the instrument does not trade.
        """
        moments = Moments()
        if now is None:
            now = moments.now()
        if self.after_days is not None:
            return now.timestamp() + self.after_days * SECONDS_IN_A_DAY
        segment = plan_order.trading_segment()
        if self.at_time is not None:
            moment, _ = moments.time_on_trading_day(self.at_time, 'at_time', segment, now)
            return moment
        if not TradingDays().is_trading_day(segment, now.date()):
            raise RefusedRequestError.refusal(
                'after_minutes are counted from now and today is not a trading day for this instrument; give at_time instead',
                400,
            )
        return moments.minutes_from_now(self.after_minutes, 'after_minutes', now)

    def bounds(self, state):
        """Whether the end applies to an order in this state.

        Args:
            state (str | None): The part's state.

        Returns:
            bool: True when the order should end.
        """
        if state in WAITING_STATES:
            return self.applies_to in ('waiting', 'both')
        if state == 'working':
            return self.applies_to in ('working', 'both')
        return False

    def described(self):
        """This lifetime as a dry run shows it.

        Returns:
            dict: The settings.
        """
        described = {
            'applies_to': self.applies_to,
            'on_end': self.on_end,
        }
        if self.at_time is not None:
            described['at_time'] = self.at_time
        elif self.after_days is not None:
            described['after_days'] = self.after_days
        else:
            described['after_minutes'] = self.after_minutes
        return described
