"""Shows a finished leg being forgotten, a refused move not holding the order back, and a throttle turned off with zero.

Three smaller behaviours are shown here. First, `forget` drops a finished leg's memory, so if the same leg id were ever asked about again it would be allowed straight away. Second, only `record` starts the waiting period, so a move the broker refused (and which is therefore never recorded) does not make the next attempt wait. Third, a minimum gap of zero turns the throttle off, and every move is allowed however close together they are.

Times are passed with `now=` so the output never depends on the machine's clock. No stand-ins are needed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/repricing_throttle/RepricingThrottle/example_2_forgetting_and_turned_off.py
"""

from unified_broker_interface.utilities.order_engine.utilities.repricing_throttle import (
    RepricingThrottle,
)


class ForgettingAndTurnedOffExample:
    """Shows forgetting a leg, an unrecorded refusal and a switched-off throttle.

    Attributes:
        throttle (RepricingThrottle): A throttle with a one-second gap.
        switched_off (RepricingThrottle): A throttle with a zero gap.
    """

    def __init__(self):
        """Builds one working throttle and one switched off.

        Returns:
            None: This method returns nothing.
        """
        self.throttle = RepricingThrottle(1.0)
        self.switched_off = RepricingThrottle(0)

    def run(self):
        """Prints the answers for each of the three cases.

        Returns:
            None: This method returns nothing.
        """
        self.throttle.record('P7-L1', now=10.0)
        print(f'P7-L1 at 10.2s, just moved: {self.throttle.allows("P7-L1", now=10.2)}')
        self.throttle.forget('P7-L1')
        print(f'P7-L1 at 10.3s, after forget: {self.throttle.allows("P7-L1", now=10.3)}')
        print(f'P8-L1 at 20.0s, broker refuses the move: {self.throttle.allows("P8-L1", now=20.0)}')
        print(f'P8-L1 at 20.1s, trying again: {self.throttle.allows("P8-L1", now=20.1)}')
        print(f'Working throttle counts: {self.throttle.counts()}')
        for moment in [
            0.0,
            0.01,
            0.02,
        ]:
            self.switched_off.record('P9-L1', now=moment)
            print(f'Switched off, P9-L1 at {moment}s: {self.switched_off.allows("P9-L1", now=moment)}')
        print(f'Switched-off throttle counts: {self.switched_off.counts()}')


if __name__ == '__main__':
    ForgettingAndTurnedOffExample().run()
