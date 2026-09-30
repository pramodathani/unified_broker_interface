"""Reads the per-broker rate setting and sends a burst of orders that has to wait briefly for room.

The rate budget allows a fixed number of order messages to each broker within a sliding window, one second in production. The limits come from the setting `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND`, whose text is a default followed by `broker=number` overrides; `limits_from_text` turns that text into numbers. `take` then counts one message, and when the window is full it waits a little for the oldest message to leave rather than refusing at once.

This program reads the text `4,zerodha=2`, so Zerodha may be sent two messages a window and every other broker four. To keep the run short, it uses a window of a tenth of a second instead of one second. Three messages to Zerodha in a row therefore make the third wait about a tenth of a second, while three to Dhan pass straight away.

The real budget keeps its windows in Redis sorted sets and counts them in a Lua script. A small stand-in replaces the Redis client: its `register_script` returns a method that does what that script does, over lists of times in memory, using this machine's monotonic clock in place of the Redis server's. The program prints only whether each message was allowed and the budget's counts, never a duration, so its output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/rate_budget/RateBudget/example_1_waiting_for_room_in_a_busy_window.py
"""

import logging
import time

from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)


class SlidingWindowRedis:
    """A stand-in for the Redis client that runs the rate budget's window script in memory.

    Attributes:
        windows (dict): Each window key to the monotonic times, in microseconds, of the messages counted in it.
    """

    def __init__(self):
        """Builds the stand-in with every window empty.

        Returns:
            None: This method returns nothing.
        """
        self.windows = {}

    def register_script(self, script_text):
        """Returns a callable that does what the rate window script does.

        Args:
            script_text (str): The script's Lua source, which the stand-in does not run.

        Returns:
            object: The stand-in's `run_window_script` method.
        """
        return self.run_window_script

    def run_window_script(self, keys, args):
        """Counts one message in every named window if all have room, or says how long until they do.

        Args:
            keys (list): The window keys.
            args (list): A member name, then a window length in microseconds and a limit for each key.

        Returns:
            int: 0 when counted, otherwise the microseconds until there is room.
        """
        now = int(time.monotonic() * 1000000)
        longest_wait = 0
        for position, key in enumerate(keys):
            window = int(args[position * 2 + 1])
            limit = float(args[position * 2 + 2])
            kept = []
            for moment in self.windows.get(key, []):
                if moment > now - window:
                    kept.append(moment)
            self.windows[key] = kept
            if len(kept) >= limit:
                wait = kept[0] + window - now
                if wait > longest_wait:
                    longest_wait = wait
        if longest_wait > 0:
            return longest_wait
        for key in keys:
            self.windows[key].append(now)
        return 0


class WaitingForRoomExample:
    """Sends three messages each to Zerodha and Dhan through one budget.

    Attributes:
        limits_read (tuple): The default limit and the overrides read from the setting's text.
        budget (RateBudget): The budget being shown.
    """

    def __init__(self):
        """Reads the limits from text and builds the budget with a tenth-of-a-second window.

        Returns:
            None: This method returns nothing.
        """
        broker_names = [
            'dhan',
            'zerodha',
        ]
        default_limit, overrides = RateBudget.limits_from_text('4,zerodha=2', broker_names)
        self.limits_read = (
            default_limit,
            overrides,
        )
        self.budget = RateBudget(
            SlidingWindowRedis(),
            0,
            default_limit,
            0.5,
            logging.getLogger('example'),
            window_seconds=0.1,
            per_broker_overrides=overrides,
        )

    def run(self):
        """Prints each broker's limit, whether each message was allowed, and the counts.

        Returns:
            None: This method returns nothing.
        """
        print(f'Default limit and overrides: {self.limits_read}')
        broker_names = [
            'zerodha',
            'dhan',
        ]
        for broker_name in broker_names:
            print(f'{broker_name} limit per window: {self.budget.limit_for(broker_name)}')
            for number in range(1, 4):
                allowed = self.budget.take(broker_name)
                print(f'  Message {number}: allowed {allowed}')
            print(f'  Counts so far: {self.budget.counts()}')


if __name__ == '__main__':
    WaitingForRoomExample().run()
