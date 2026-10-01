"""The execution that sizes slices by how busy the market usually is: a volume-weighted average price order."""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import (
    moments,
)
from unified_broker_interface.utilities.order_engine.utilities.timed_slices_execution import (
    TimedSlicesExecution,
)

SESSION_OPENS_AT = datetime.time(9, 15)
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
    """A plan order's execution whose slices are sized by a volume profile, one relative weight per half hour from the 09:15 open, as today's VWAP type does.

    A slice takes the weight of the half hour it falls in, so slices near the busy open and close are bigger. With no `volume_profile` the default is today's NSE equity shape. A slice that falls after the last half hour takes the last weight.

    Attributes:
        profile (tuple): One relative weight per half hour.
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

    def bucket_of(self, moment):
        """The half hour from the open that a moment falls in.

        Args:
            moment (float): A Unix time.

        Returns:
            int: The half hour, counting from zero; zero before the open.
        """
        when = datetime.datetime.fromtimestamp(moment, moments.INDIA)
        opens = when.replace(
            hour=SESSION_OPENS_AT.hour,
            minute=SESSION_OPENS_AT.minute,
            second=0,
            microsecond=0,
        )
        minutes = (when - opens).total_seconds() / 60
        if minutes < 0:
            return 0
        return int(minutes // BUCKET_MINUTES)

    def slice_weights(self, memory):
        """Each slice's weight, from the half hour it falls in.

        Args:
            memory (dict): The execution's memory, holding when the schedule started.

        Returns:
            list: One weight per slice.
        """
        started_at = memory.get('started_at')
        if started_at is None:
            return [1.0] * self.slices
        weights = []
        for index in range(self.slices):
            bucket = min(self.bucket_of(started_at + self.interval(memory) * index), len(self.profile) - 1)
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
