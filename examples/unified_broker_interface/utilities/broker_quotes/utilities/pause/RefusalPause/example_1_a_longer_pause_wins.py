"""Pauses a broker's quote endpoint, reads how long is left, and shows that a shorter pause never cuts a longer one short.

A quote source keeps one `RefusalPause` for its broker. When the broker refuses in a way that asking again would make worse, such as a rate limit or a ban on the address, the source calls `pause` with a number of seconds and a reason, and before every later request it calls `remaining`, which returns the seconds left and the reason, or None when calling is allowed again.

This program first pauses for thirty minutes, as Fyers' source does after Cloudflare's block page, and then asks for a five minute pause, as after an ordinary rate limit. The thirty minute pause and its reason are kept. The pause reads the real clock, so the seconds left are printed rounded to whole seconds, which keeps the output the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/pause/RefusalPause/example_1_a_longer_pause_wins.py
"""

from unified_broker_interface.utilities.broker_quotes.utilities.pause import (
    RefusalPause,
)


class LongerPauseWinsExample:
    """Applies a long pause and then a short one, printing what remains after each.

    Attributes:
        pause (RefusalPause): The pause being shown.
    """

    def __init__(self):
        """Builds a pause with nothing in force.

        Returns:
            None: This method returns nothing.
        """
        self.pause = RefusalPause()

    def describe(self):
        """Describes what the pause says right now.

        Returns:
            str: The rounded seconds left and the reason, or a note that calling is allowed.
        """
        remaining = self.pause.remaining()
        if remaining is None:
            return 'calling is allowed'
        seconds_left, reason = remaining
        return f'paused for about {round(seconds_left)} more seconds because {reason}'

    def run(self):
        """Prints the pause's state before and after each call to `pause`.

        Returns:
            None: This method returns nothing.
        """
        print(f'Before any refusal: {self.describe()}')
        self.pause.pause(1800, 'Cloudflare blocked this address')
        print(f'After a block: {self.describe()}')
        self.pause.pause(300, 'rate limited')
        print(f'After a rate limit: {self.describe()}')


if __name__ == '__main__':
    LongerPauseWinsExample().run()
