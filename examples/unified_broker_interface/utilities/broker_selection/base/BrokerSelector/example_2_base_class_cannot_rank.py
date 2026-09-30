"""Shows that `BrokerSelector` itself cannot rank brokers, and what its default hooks do when a subclass leaves them alone.

`BrokerSelector` is the interface every selection algorithm implements, so it has no name and no ranking of its own: `NAME` is None and `ranked_brokers` raises `NotImplementedError`. The API picks a selector by name from its registry, so a base-class instance is never used for real orders. This program builds one anyway, to show those two facts, and then calls the three reporting hooks, which the base class accepts and ignores, and `passed_over_reason`, which never rules a broker out.

The selector is given an empty broker cost table and a stand-in Redis client that records any command it is sent. Nothing touches a data store.

Notice the error message is empty, because the base class raises a bare `NotImplementedError`, and that the stand-in Redis client received no command.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/base/BrokerSelector/example_2_base_class_cannot_rank.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.base import (
    BrokerSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)


class RecordingRedis:
    """A stand-in for the Redis client that records every command it is sent.

    Attributes:
        commands (list): The commands received, as tuples of name and arguments.
    """

    def __init__(self):
        """Builds the stand-in with no commands recorded.

        Returns:
            None: This method returns nothing.
        """
        self.commands = []

    def incrby(self, key, amount):
        """Records an increment.

        Args:
            key (str): The key to increment.
            amount (int): How much to add.

        Returns:
            int: The amount, as if the key had been zero.
        """
        self.commands.append((
            'incrby',
            key,
            amount,
        ))
        return amount


class BaseClassCannotRankExample:
    """Asks the base selector to rank a rotation and to record a choice.

    Attributes:
        selector (BrokerSelector): The base-class selector being shown.
        cache (RecordingRedis): The stand-in Redis client.
    """

    def __init__(self):
        """Builds a base-class selector around an empty cost table.

        Returns:
            None: This method returns nothing.
        """
        cost_table = BrokerCostTable(logging.getLogger('example'))
        self.selector = BrokerSelector(cost_table)
        self.cache = RecordingRedis()

    def run(self):
        """Prints the base class's name, its failed ranking and its silent hooks.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name: {BrokerSelector.NAME}')
        rotation = [
            'dhan',
            'zerodha',
        ]
        try:
            self.selector.ranked_brokers(None, None, rotation, [])
        except NotImplementedError as error:
            print(f'ranked_brokers raised {type(error).__name__} with message {str(error)!r}')
        self.selector.record_chosen('zerodha')
        self.selector.record_passed_over(self.cache, 1)
        self.selector.record_outcome('zerodha', None)
        print(f'Commands sent to Redis by the hooks: {self.cache.commands}')
        print(f'Reason to pass over zerodha: {self.selector.passed_over_reason("zerodha")}')


if __name__ == '__main__':
    BaseClassCannotRankExample().run()
