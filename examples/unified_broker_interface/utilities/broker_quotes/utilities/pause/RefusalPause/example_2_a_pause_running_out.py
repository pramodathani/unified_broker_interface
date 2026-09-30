"""Shows a short pause running out, after which the broker may be called again.

`RefusalPause.remaining` returns None once the pause's end has passed, so a quote source that checks it before every request starts sending again on its own, with nothing to reset. This program pauses for a fifth of a second, checks straight away, waits three tenths of a second, and checks again.

Several threads of one web worker share a source, and so its pause; the pause guards its state with a lock, so `pause` and `remaining` can be called from any of them. The program uses one thread only. It reads the real clock, so it prints whether a pause is in force rather than the exact fraction of a second left.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/pause/RefusalPause/example_2_a_pause_running_out.py
"""

import time

from unified_broker_interface.utilities.broker_quotes.utilities.pause import (
    RefusalPause,
)


class PauseRunningOutExample:
    """Applies a very short pause and watches it run out.

    Attributes:
        pause (RefusalPause): The pause being shown.
    """

    def __init__(self):
        """Builds a pause with nothing in force.

        Returns:
            None: This method returns nothing.
        """
        self.pause = RefusalPause()

    def run(self):
        """Prints whether the pause is in force just after it starts and after it ends.

        Returns:
            None: This method returns nothing.
        """
        self.pause.pause(0.2, 'rate limited')
        remaining = self.pause.remaining()
        print(f'Straight away: in force {remaining is not None}, reason {remaining[1]!r}')
        time.sleep(0.3)
        print(f'After 0.3 seconds: {self.pause.remaining()}')


if __name__ == '__main__':
    PauseRunningOutExample().run()
