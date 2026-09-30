"""Refuses a new order once the day's profit and loss is past the configured loss limit.

`LossLockout` reads the funds document that `bin/unified/portfolio/funds` keeps in Redis under `unified:portfolio:funds`, adds the realized and unrealized profit and loss together, and refuses new orders once that total is a loss at least as large as the limit.

A small stand-in replaces the Redis client. It holds one funds document as a JSON string, exactly as the real key does, and the program rewrites it between checks to play out a day going wrong: first a small loss, then a loss of exactly the limit, then a bigger one. The limit is 5,000 rupees.

Notice that unrealized losses count: at the second check nothing has been realized past the limit, but an open position is losing enough to reach it. `locked_out` counts the refusals.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/loss_lockout/LossLockout/example_1_day_down_past_the_limit.py
"""

import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.loss_lockout import (
    LossLockout,
)


class FundsRedis:
    """A stand-in for the Redis client that holds one funds document.

    Attributes:
        values (dict): The stored strings, by key.
    """

    def __init__(self):
        """Builds the stand-in with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}

    def get(self, key):
        """Reads one stored string.

        Args:
            key (str): The key.

        Returns:
            str | None: The stored string, or None when the key is missing.
        """
        return self.values.get(key)

    def store_funds(self, realized, unrealized):
        """Writes a funds document with the given profit and loss.

        Args:
            realized (float): The realized profit and loss.
            unrealized (float): The unrealized profit and loss.

        Returns:
            None: This method returns nothing.
        """
        document = {
            'pnl': {
                'realized': realized,
                'unrealized': unrealized,
            },
        }
        self.values['unified:portfolio:funds'] = json.dumps(document)


class DayDownPastTheLimitExample:
    """Checks the lockout at three points of a losing day.

    Attributes:
        cache (FundsRedis): The stand-in Redis client.
        lockout (LossLockout): The lockout being shown.
        moments (list): The (realized, unrealized) pairs to check, in order.
    """

    def __init__(self):
        """Builds the lockout with a 5,000 rupee limit.

        Returns:
            None: This method returns nothing.
        """
        self.cache = FundsRedis()
        self.lockout = LossLockout(self.cache, 5000.0, logging.getLogger('example'))
        self.moments = [
            (
                -1200.0,
                300.0,
            ),
            (
                -1500.0,
                -3500.0,
            ),
            (
                -4000.0,
                -2250.5,
            ),
        ]

    def run(self):
        """Prints the day's profit and the lockout's answer at each moment.

        Returns:
            None: This method returns nothing.
        """
        print(f'Configured: {self.lockout.is_configured()}')
        for realized, unrealized in self.moments:
            self.cache.store_funds(realized, unrealized)
            print(f'Realized {realized}, unrealized {unrealized}')
            print(f'  Day profit: {self.lockout.day_profit()}')
            print(f'  Refusal: {self.lockout.refusal_reason()}')
        print(f'Orders locked out: {self.lockout.locked_out}')


if __name__ == '__main__':
    DayDownPastTheLimitExample().run()
