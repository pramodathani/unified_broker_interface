"""The execution that sends equal slices on a clock: a time-weighted average price order."""

from unified_broker_interface.utilities.order_engine.utilities.timed_slices_execution import (
    TimedSlicesExecution,
)


class TwapExecution(TimedSlicesExecution):
    """A plan order's execution that sends equal slices at even intervals, as today's TWAP type does."""

    NAME = 'twap'

    def slice_weights(self, memory):
        """Every slice the same.

        Args:
            memory (dict): Unused.

        Returns:
            list: One weight of 1.0 per slice.
        """
        del memory
        return [1.0] * self.slices
