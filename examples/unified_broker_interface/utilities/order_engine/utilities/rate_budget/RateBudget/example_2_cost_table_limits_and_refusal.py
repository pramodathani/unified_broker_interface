"""Takes a broker's rate limits from the cost table, refuses a message once the wait runs out, and rejects a misspelt setting.

When the budget is given a `BrokerCostTable`, a broker's per-second limit comes from its row and replaces the configured one, and its per-minute and per-hour limits add longer windows that are counted in the same step. `limit_for` and `longer_windows_for` show what the budget will count. A broker with no row keeps the configured limit.

The program builds a table in memory with one row for Zerodha, allowing one message a second and three a minute, so nothing reads the database. It sends two messages to Zerodha back to back with a wait of only 0.05 seconds. The second finds the one-second window full, waits out its 0.05 seconds, and is refused with a logged warning; `counts` shows the refusal. A small stand-in replaces the Redis client and runs the window script in memory, and another replaces the logger so the warning appears in the output.

Finally, `limits_from_text` is given a setting with a misspelt broker name. It raises `ValueError` rather than quietly running that broker at the default rate.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/rate_budget/RateBudget/example_2_cost_table_limits_and_refusal.py
"""

import decimal
import logging
import time

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)
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


class PrintingLogger:
    """A stand-in for a logger that prints each warning."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The warning.

        Returns:
            None: This method returns nothing.
        """
        print(f'  WARNING {message}')


class CostTableLimitsExample:
    """Builds a budget over a one-row cost table and sends it more than it allows.

    Attributes:
        cache (SlidingWindowRedis): The stand-in Redis client.
        budget (RateBudget): The budget being shown.
    """

    def __init__(self):
        """Builds the cost table and the budget.

        Returns:
            None: This method returns nothing.
        """
        fees = {
            'delivery': decimal.Decimal('0'),
            'fno': decimal.Decimal('20'),
            'intraday': decimal.Decimal('20'),
        }
        rows = {
            'zerodha': BrokerCosts('zerodha', 1, 3, None, 3000, fees),
        }
        cost_table = BrokerCostTable(logging.getLogger('example'), rows)
        self.cache = SlidingWindowRedis()
        self.budget = RateBudget(
            self.cache,
            0,
            10,
            0.05,
            PrintingLogger(),
            window_seconds=1.0,
            cost_table=cost_table,
        )

    def run(self):
        """Prints the limits, the two messages' answers, the counts and the setting error.

        Returns:
            None: This method returns nothing.
        """
        print(f'zerodha limit per second: {self.budget.limit_for("zerodha")}')
        print(f'zerodha longer windows: {self.budget.longer_windows_for("zerodha")}')
        print(f'fyers limit per second: {self.budget.limit_for("fyers")}')
        print(f'fyers longer windows: {self.budget.longer_windows_for("fyers")}')
        print('Sending two messages to zerodha:')
        print(f'  First: allowed {self.budget.take("zerodha")}')
        second = self.budget.take('zerodha')
        print(f'  Second: allowed {second}')
        print(f'Windows counted: {sorted(self.cache.windows)}')
        print(f'Counts: {self.budget.counts()}')
        broker_names = [
            'dhan',
            'zerodha',
        ]
        try:
            RateBudget.limits_from_text('10,zerodah=5', broker_names)
        except ValueError as error:
            print(f'Misspelt setting refused: {error}')


if __name__ == '__main__':
    CostTableLimitsExample().run()
