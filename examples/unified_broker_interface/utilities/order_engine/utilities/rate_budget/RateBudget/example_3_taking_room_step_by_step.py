"""Spells out what `take` does in its loop, using the budget's smaller steps, and shows a stopping process cutting a wait short.

`take` is built from four smaller methods. `try_take` counts a message if there is room and otherwise answers how many microseconds until there is. `pause` waits that long, but answers True at once if the process has been asked to stop. `count_waited` and `count_refused` keep the tallies that `counts` reports. This program calls them one by one, the way `take` does, so each step can be seen.

The budget allows one message to Kotak per window, and the window is shortened to a tenth of a second so the program runs quickly. The first message fits, the second has to wait, a pause of 0.12 seconds lets the window empty, and the retry fits and is counted as waited. Then the window is full again and the stop event is set, as it would be when the engine is shutting down: `pause` returns True without sleeping, and `take` itself refuses straight away when given that event.

A small stand-in replaces the Redis client and runs the window script in memory. The program never prints a wait's length, only whether there was one, so its output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/rate_budget/RateBudget/example_3_taking_room_step_by_step.py
"""

import logging
import threading
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


class TakingRoomStepByStepExample:
    """Walks through one wait that succeeds and one that is cut short.

    Attributes:
        budget (RateBudget): The budget being shown.
        stop (threading.Event): The event a stopping process sets.
    """

    def __init__(self):
        """Builds a budget of one message per tenth of a second to each broker.

        Returns:
            None: This method returns nothing.
        """
        self.budget = RateBudget(
            SlidingWindowRedis(),
            0,
            1,
            5.0,
            logging.getLogger('example'),
            window_seconds=0.1,
        )
        self.stop = threading.Event()

    def run(self):
        """Prints the answer of each step.

        Returns:
            None: This method returns nothing.
        """
        print(f'First try: wait {self.budget.try_take("kotak")} microseconds')
        wait_microseconds = self.budget.try_take('kotak')
        print(f'Second try must wait: {wait_microseconds > 0}')
        stopping = self.budget.pause(0.12, self.stop)
        print(f'Paused 0.12 seconds, stopping: {stopping}')
        wait_microseconds = self.budget.try_take('kotak')
        print(f'Retry: wait {wait_microseconds} microseconds')
        self.budget.count_waited()
        print(f'Counts: {self.budget.counts()}')
        print(f'Next try must wait: {self.budget.try_take("kotak") > 0}')
        self.stop.set()
        stopping = self.budget.pause(0.12, self.stop)
        print(f'Stop event set, pause answers stopping: {stopping}')
        self.budget.count_refused()
        print(f'take with the stop event set: allowed {self.budget.take("kotak", self.stop)}')
        print(f'Counts: {self.budget.counts()}')


if __name__ == '__main__':
    TakingRoomStepByStepExample().run()
