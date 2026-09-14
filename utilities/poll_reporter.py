"""
Logging for loops that poll every half second, where a line per cycle would bury the journal.

The REST pollers in `bin/<broker>/` and the combiners in `bin/unified/` report each cycle's outcome - "Merged 0 of 0
order(s)", "Orders poll failed: ..." - and at two cycles a second that is about 170,000 lines a day per script, nearly
all of them the same line. `PollReporter` logs a message when it differs from the last one it logged at that level, and
otherwise repeats it once every `interval` seconds, so the journal shows every change and a steady heartbeat while
nothing changes.
"""

import time
import logging

class PollReporter:
    """
    Log a polling loop's outcomes when they change, and at most once every `interval` seconds while they do not.

    - `logger` is where the messages go.
    - `interval` is how often an unchanged message is repeated, in seconds.
    """

    def __init__(self, logger, interval=60):
        self.logger = logger
        self.interval = interval
        # The last message logged at each level, and when.
        self.last = {}

    def log(self, level, message):
        """
        Log `message` at `level` when it is not the message last logged at that level, or that one is `interval` old.

        - `level` is a `logging` level, for example `logging.INFO`.
        - `message` is the text to log.
        """
        now = time.monotonic()
        previous = self.last.get(level)
        if previous is None or previous[0] != message or now - previous[1] >= self.interval:
            self.logger.log(level, message)
            self.last[level] = (message, now)

    def info(self, message):
        """Log a cycle's outcome at INFO, when it changed or once an interval. `message` is the text."""
        self.log(logging.INFO, message)

    def error(self, message):
        """Log a failed cycle at ERROR, when the failure changed or once an interval. `message` is the text."""
        self.log(logging.ERROR, message)
