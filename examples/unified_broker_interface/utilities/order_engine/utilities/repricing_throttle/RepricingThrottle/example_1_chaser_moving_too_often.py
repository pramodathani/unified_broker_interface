"""Shows the throttle refusing a chasing order's moves that come too soon after the last one.

A chasing order moves its resting price every time the best bid moves, which on a liquid instrument is several times a second. The engine asks `allows` before sending a move and calls `record` only after the broker accepted it. With a minimum gap of half a second, any move asked for sooner than that after the last accepted one is refused.

The throttle normally reads `time.monotonic()`, which would make the output depend on how fast the machine is. This program passes `now=` explicitly on every call so the timeline is fixed: the bid moves at 0.0, 0.1, 0.3, 0.6 and 1.3 seconds. No other stand-ins are needed.

Notice that the moves at 0.1 and 0.3 seconds are refused, the one at 0.6 is allowed because 0.6 seconds have passed since the accepted move at 0.0, and `counts` ends with three allowed and two suppressed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/repricing_throttle/RepricingThrottle/example_1_chaser_moving_too_often.py
"""

from unified_broker_interface.utilities.order_engine.utilities.repricing_throttle import (
    RepricingThrottle,
)


class ChaserMovingTooOftenExample:
    """Asks the throttle about a series of moves of one leg on a fixed timeline.

    Attributes:
        throttle (RepricingThrottle): The throttle being shown.
        leg_id (str): The leg being moved.
        move_times (list): The monotonic times at which the market moved.
    """

    def __init__(self):
        """Builds a throttle with a half-second minimum gap.

        Returns:
            None: This method returns nothing.
        """
        self.throttle = RepricingThrottle(0.5)
        self.leg_id = 'P1-L1'
        self.move_times = [
            0.0,
            0.1,
            0.3,
            0.6,
            1.3,
        ]

    def run(self):
        """Prints whether each move is allowed, then the throttle's counts.

        Returns:
            None: This method returns nothing.
        """
        for moment in self.move_times:
            allowed = self.throttle.allows(self.leg_id, now=moment)
            if allowed:
                self.throttle.record(self.leg_id, now=moment)
                print(f'{moment:.1f}s: move sent')
            else:
                print(f'{moment:.1f}s: too soon, move suppressed')
        print(f'Counts: {self.throttle.counts()}')


if __name__ == '__main__':
    ChaserMovingTooOftenExample().run()
