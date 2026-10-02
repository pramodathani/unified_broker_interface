"""The execution that sizes slices by how busy the market usually is: a volume-weighted average price order."""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import (
    moments,
)
from unified_broker_interface.utilities.order_engine.utilities.session_open import (
    EQUITY_OPENS_AT,
)
from unified_broker_interface.utilities.order_engine.utilities.session_open import (
    SessionOpen,
)
from unified_broker_interface.utilities.order_engine.utilities.timed_slices_execution import (
    TimedSlicesExecution,
)

BUCKET_MINUTES = 30
DEFAULT_PROFILE = (
    0.145,
    0.095,
    0.075,
    0.065,
    0.058,
    0.052,
    0.048,
    0.048,
    0.052,
    0.058,
    0.068,
    0.093,
    0.143,
)


class VwapExecution(TimedSlicesExecution):
    """A plan order's execution whose slices are sized by a volume profile, one relative weight per half hour from the session's open, as today's VWAP type does.

    A slice takes the weight of the half hour it falls in, so slices near the busy open and close are bigger. The half hours count from the segment's own open, 09:15 for equity and 09:00 for currency and MCX, on the day the order started working. With no `volume_profile` the default is today's NSE equity shape, used only for equity; a currency or commodity order with no profile of its own gets even slices. A slice that falls after the last half hour takes the last weight.

    Attributes:
        profile (tuple): One relative weight per half hour.
        profile_given (bool): Whether the caller gave the profile, rather than taking the equity default.
    """

    NAME = 'vwap'

    def __init__(self, slices, over_minutes, profile):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            slices (int): How many slices.
            over_minutes (float): The minutes to spread them across.
            profile (tuple | None): The volume profile, or None for the default.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(slices, over_minutes)
        self.profile = tuple(profile) if profile is not None else DEFAULT_PROFILE
        self.profile_given = profile is not None

    def begin(self, plan_order, memory, quotes, now):
        """Starts the clock and remembers the session the half hours count from.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which knows its segment.
            memory (dict): The execution's memory, given `started_at`, `opens_at` and `equity`.
            quotes (dict): Unused.
            now (float): The Unix time the order started working.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when it starts after `until`.
        """
        session = SessionOpen(plan_order.trading_segment())
        super().begin(plan_order, memory, quotes, now)
        memory['opens_at'] = session.opens_at().isoformat()
        memory['equity'] = session.is_equity()

    def bucket_of(self, moment, opens_at=EQUITY_OPENS_AT, anchored_at=None):
        """The half hour from the open that a moment falls in.

        Args:
            moment (float): A Unix time.
            opens_at (datetime.time): When the session opens, 09:15 for equity unless told otherwise.
            anchored_at (float | None): A Unix time on the day whose open is counted from, such as when the order started working, or None for the moment's own day.

        Returns:
            int: The half hour, counting from zero; zero before the open.
        """
        when = datetime.datetime.fromtimestamp(moment, moments.INDIA)
        anchor = when
        if anchored_at is not None:
            anchor = datetime.datetime.fromtimestamp(anchored_at, moments.INDIA)
        opens = anchor.replace(
            hour=opens_at.hour,
            minute=opens_at.minute,
            second=0,
            microsecond=0,
        )
        minutes = (when - opens).total_seconds() / 60
        if minutes < 0:
            return 0
        return int(minutes // BUCKET_MINUTES)

    def slice_weights(self, memory):
        """Each slice's weight, from the half hour it falls in, or even weights for a currency or commodity order with no profile of its own.

        Args:
            memory (dict): The execution's memory, holding when the schedule started, when the session opens and whether it is equity.

        Returns:
            list: One weight per slice.
        """
        started_at = memory.get('started_at')
        if started_at is None:
            return [1.0] * self.slices
        if not self.profile_given and memory.get('equity') is False:
            return [1.0] * self.slices
        opens_at = EQUITY_OPENS_AT
        if memory.get('opens_at'):
            opens_at = datetime.time.fromisoformat(memory['opens_at'])
        weights = []
        for index in range(self.slices):
            bucket = min(self.bucket_of(started_at + self.interval(memory) * index, opens_at, started_at), len(self.profile) - 1)
            weights.append(self.profile[bucket])
        return weights

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        described = super().described()
        described[self.NAME]['volume_profile'] = list(self.profile)
        return described
