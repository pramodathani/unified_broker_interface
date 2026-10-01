"""The execution that sends larger slices first: an implementation shortfall order."""

from unified_broker_interface.utilities.order_engine.utilities.timed_slices_execution import (
    TimedSlicesExecution,
)

MOST_DECAY = 0.5


class FrontLoadedExecution(TimedSlicesExecution):
    """A plan order's execution whose slices shrink by a fixed share each time, so most of the order trades early, as today's implementation shortfall type does.

    Each slice is `1 - urgency × 0.5` of the one before: an urgency of 0 is an even split, and an urgency of 1 halves every slice.

    Attributes:
        urgency (float): How front-loaded the schedule is, from 0 to 1.
    """

    NAME = 'front_loaded'

    def __init__(self, slices, over_minutes, urgency):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            slices (int): How many slices.
            over_minutes (float): The minutes to spread them across.
            urgency (float): How front-loaded, from 0 to 1.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(slices, over_minutes)
        self.urgency = urgency

    def slice_weights(self, memory):
        """Weights that decay geometrically from the first slice.

        Args:
            memory (dict): Unused.

        Returns:
            list: One weight per slice, each `1 - urgency × 0.5` of the one before.
        """
        del memory
        decay = 1 - self.urgency * MOST_DECAY
        weights = []
        weight = 1.0
        for _ in range(self.slices):
            weights.append(weight)
            weight = weight * decay
        return weights

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        described = super().described()
        described[self.NAME]['urgency'] = self.urgency
        return described
