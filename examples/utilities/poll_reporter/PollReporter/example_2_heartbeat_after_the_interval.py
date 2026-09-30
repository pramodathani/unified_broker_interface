"""Shows the heartbeat: an unchanged message is logged again once the interval has passed, and each level keeps its own memory.

A `PollReporter` remembers the last message it logged at each level and when. An unchanged message is logged again once `interval` seconds have passed since it was last logged, so the journal shows the loop is still alive. Levels are tracked separately, so `log` with `logging.WARNING` does not reset what `info` remembers.

To keep the program short, the interval is 0.5 seconds and the program sleeps 0.6 seconds between two groups of cycles, instead of the pollers' 60 seconds. The logger writes to the output through a handler that prints the level and message without a timestamp. Nothing is polled.

Notice that the second group repeats "Positions unchanged" once, right after the pause, and then goes quiet again, and that the WARNING and INFO lines do not silence each other.

Run it from the project root:

    python examples/utilities/poll_reporter/PollReporter/example_2_heartbeat_after_the_interval.py
"""

import logging
import sys
import time

from utilities.poll_reporter import (
    PollReporter,
)


class HeartbeatAfterTheIntervalExample:
    """Reports two groups of cycles with a pause longer than the interval between them.

    Attributes:
        reporter (PollReporter): The reporter being shown.
    """

    def __init__(self):
        """Builds a logger that prints to the output and a reporter with a 0.5 second interval.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example.positions_poller')
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('  logged %(levelname)s: %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.reporter = PollReporter(logger, interval=0.5)

    def one_group(self, label):
        """Reports three unchanged cycles with a warning between them.

        Args:
            label (str): The group's name, for the printout.

        Returns:
            None: This method returns nothing.
        """
        print(label)
        self.reporter.info('Positions unchanged')
        self.reporter.log(logging.WARNING, 'Dhan answered slowly')
        self.reporter.info('Positions unchanged')
        self.reporter.log(logging.WARNING, 'Dhan answered slowly')
        self.reporter.info('Positions unchanged')

    def run(self):
        """Reports two groups with a pause between them.

        Returns:
            None: This method returns nothing.
        """
        self.one_group('First group')
        time.sleep(0.6)
        self.one_group('Second group, after 0.6 seconds')
        levels = []
        for level in sorted(self.reporter.last):
            levels.append(logging.getLevelName(level))
        print(f'Levels remembered: {levels}')


if __name__ == '__main__':
    HeartbeatAfterTheIntervalExample().run()
