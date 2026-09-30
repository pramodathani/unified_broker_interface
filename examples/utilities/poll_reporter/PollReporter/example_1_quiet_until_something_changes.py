"""Reports ten polling cycles, logging only the cycles whose outcome differs from the last one logged.

The REST pollers and the unified combiners run a cycle twice a second. Logging every cycle's outcome would write about 170,000 nearly identical lines a day per script, so they report through a `PollReporter`, which logs a message only when it differs from the last message logged at that level, or when that message is at least `interval` seconds old.

This program feeds a reporter the outcomes of ten made-up order poll cycles. It uses the default one-minute interval, and the ten cycles take far less than a minute, so no unchanged message is repeated. The reporter's logger writes to the output through a handler that prints the level and message without a timestamp. Nothing is polled.

Notice that the three identical "Merged 0" cycles produce one line, that the error is logged as soon as it appears and again when its text changes, and that the INFO line after the errors is logged because it differs from the last INFO line, not because an error came between.

Run it from the project root:

    python examples/utilities/poll_reporter/PollReporter/example_1_quiet_until_something_changes.py
"""

import logging
import sys

from utilities.poll_reporter import (
    PollReporter,
)


class QuietUntilSomethingChangesExample:
    """Reports ten cycles through a reporter and prints what was logged.

    Attributes:
        reporter (PollReporter): The reporter being shown.
        outcomes (list): Each cycle's level name and message.
    """

    def __init__(self):
        """Builds a logger that prints to the output and a reporter over it.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example.orders_poller')
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('  logged %(levelname)s: %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.reporter = PollReporter(logger)
        self.outcomes = [
            (
                'info',
                'Merged 0 of 0 order(s)',
            ),
            (
                'info',
                'Merged 0 of 0 order(s)',
            ),
            (
                'info',
                'Merged 0 of 0 order(s)',
            ),
            (
                'info',
                'Merged 2 of 2 order(s)',
            ),
            (
                'error',
                'Orders poll failed: 503 Service Unavailable',
            ),
            (
                'error',
                'Orders poll failed: 503 Service Unavailable',
            ),
            (
                'error',
                'Orders poll failed: read timed out',
            ),
            (
                'info',
                'Merged 0 of 2 order(s)',
            ),
            (
                'info',
                'Merged 0 of 2 order(s)',
            ),
            (
                'info',
                'Merged 0 of 2 order(s)',
            ),
        ]

    def run(self):
        """Reports each cycle.

        Returns:
            None: This method returns nothing.
        """
        print(f'Repeat interval: {self.reporter.interval} seconds')
        for cycle, outcome in enumerate(self.outcomes, start=1):
            level_name, message = outcome
            print(f'cycle {cycle}: {level_name} {message}')
            if level_name == 'info':
                self.reporter.info(message)
            else:
                self.reporter.error(message)


if __name__ == '__main__':
    QuietUntilSomethingChangesExample().run()
