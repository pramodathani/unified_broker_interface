"""An order sliced to follow the shape of the trading day's volume."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.twap import Twap
from unified_broker_interface.utilities.order_engine.utilities import moments

SESSION_OPENS_AT = datetime.time(9, 15)
SESSION_CLOSES_AT = datetime.time(15, 30)
BUCKET_MINUTES = 30
# Fractions of an ordinary NSE equity day's volume, per half hour from the open. The shape is the
# well-known one: a burst at the open, a quiet middle, and a heavier close as the day's positions
# are settled. The last bucket is fifteen minutes rather than thirty, which is why it is as large
# as the first.
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


class Vwap(Twap):
    """A sliced order whose slices are big when the market is busy and small when it is not.

    A time-weighted order sends the same quantity every five minutes all afternoon, which means it trades the same amount at half past one, when almost nobody is trading, as it does at ten past three, when everybody is. Trading a fixed amount into a quiet market moves it; the same amount into a busy one does not. Weighting by volume is how an order of any size disappears into the day.

    The name is what it aims at: the volume weighted average price, which is the benchmark most execution is measured against, because it is roughly what the average participant paid. An order that trades in proportion to the market's own volume gets roughly that price by construction.

    **The default profile is a shape, not a measurement.** It is the ordinary Indian equity day — heavy in the first half hour, quiet across lunch, heavy again into the close — and it is a good approximation for a liquid stock and a poor one for an instrument with its own rhythm, such as a commodity that moves when a foreign market opens. Somebody who has measured their instrument passes `volume_profile`, a list of relative weights for consecutive half hours from the open, and that is used instead.

    Slices still go out on an even clock. Only their sizes differ, which keeps the whole schedule visible in advance and keeps this a small change from the type it subclasses rather than a second scheduler.
    """

    SYNTHETIC_TYPE = 'vwap'

    def read_profile(self):
        """The volume curve the slices are weighted by.

        Returns:
            tuple: One relative weight per half hour from the open.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller's profile is not a list of numbers at or above zero that add up to something.
        """
        given = self.parent.parameters.get('volume_profile')
        if given is None:
            return DEFAULT_PROFILE
        if not isinstance(given, list) or not given:
            raise RefusedRequestError.refusal(
                'volume_profile must be a list of relative weights, one per '
                'half hour from the open',
                400,
            )
        weights = []
        for value in given:
            try:
                weight = float(value)
            except (TypeError, ValueError):
                raise RefusedRequestError.refusal(
                    f'every volume_profile weight must be a number, not '
                    f'{value!r}',
                    400,
                )
            if weight < 0:
                raise RefusedRequestError.refusal(
                    f'volume_profile weights cannot be negative, not {weight}',
                    400,
                )
            weights.append(weight)
        if sum(weights) <= 0:
            raise RefusedRequestError.refusal(
                'volume_profile weights must add up to more than zero',
                400,
            )
        return tuple(weights)

    def bucket_of(self, moment):
        """Which half hour of the session a moment falls in.

        A moment before the open counts as the first bucket and one after the close as the last, so an order placed before the bell or running past it is weighted by the nearest part of the day rather than refused.

        Args:
            moment (float): The Unix time.

        Returns:
            int: The bucket, counting from zero at the open.
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

    def slice_weights(self, slices):
        """The share of the order each slice takes, from where in the day it falls.

        Args:
            slices (int): How many slices there are.

        Returns:
            list: One weight per slice.
        """
        profile = self.read_profile()
        started_at = self.parent.parameters.get('started_at')
        interval = self.parent.parameters.get('interval_seconds')
        if not isinstance(started_at, (int, float)):
            return [1.0] * slices
        if not isinstance(interval, (int, float)):
            return [1.0] * slices
        weights = []
        for index in range(slices):
            bucket = self.bucket_of(started_at + interval * index)
            bucket = min(bucket, len(profile) - 1)
            weights.append(profile[bucket])
        return weights
