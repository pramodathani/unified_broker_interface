"""Offers four orders in a row to four brokers, each order starting at the next broker's turn.

A `RoundRobinSelector` keeps its turn counter in the Redis key `unified:orders:round_robin`, so every gunicorn worker and the order engine share one rotation. For each order it queues one `INCR` of that counter on the pipeline the route is already sending, and ranks the rotation starting at the counter modulo the number of brokers.

This program replaces Redis with a small stand-in that keeps the counter in a dictionary, and a stand-in pipeline that queues the increment and applies it when executed, as a real pipeline does. Every broker accepts every order here, so nothing is passed over.

Notice that the counter goes up by one per order and that the first broker in each ranking moves one place along the rotation each time, wrapping round after Zerodha.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/round_robin/RoundRobinSelector/example_1_taking_turns.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.round_robin import (
    RoundRobinSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)


class CounterRedis:
    """A stand-in for the Redis client that keeps integer keys in a dictionary.

    Attributes:
        values (dict): The value (int) of each key.
    """

    def __init__(self):
        """Builds the stand-in with no keys.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}

    def incrby(self, key, amount):
        """Adds to a key, as Redis `INCRBY` does.

        Args:
            key (str): The key.
            amount (int): How much to add.

        Returns:
            int: The key's new value.
        """
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]

    def pipeline(self):
        """Starts a pipeline over this stand-in.

        Returns:
            CounterPipeline: The new pipeline.
        """
        return CounterPipeline(self)


class CounterPipeline:
    """A stand-in for a Redis pipeline that queues increments and applies them on `execute`.

    Attributes:
        cache (CounterRedis): The stand-in Redis the commands are applied to.
        queued (list): The keys queued for an increment.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (CounterRedis): The stand-in Redis.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.queued = []

    def incr(self, key):
        """Queues an increment by one.

        Args:
            key (str): The key.

        Returns:
            CounterPipeline: This pipeline.
        """
        self.queued.append(key)
        return self

    def execute(self):
        """Applies every queued increment.

        Returns:
            list: Each key's value after its increment, in order.
        """
        replies = []
        for key in self.queued:
            replies.append(self.cache.incrby(key, 1))
        self.queued = []
        return replies


class TakingTurnsExample:
    """Ranks the rotation for four orders in a row.

    Attributes:
        selector (RoundRobinSelector): The selector being shown.
        cache (CounterRedis): The stand-in Redis client.
        rotation (list): The broker names not excluded by configuration, in turn order.
    """

    def __init__(self):
        """Builds the selector and the stand-in Redis.

        Returns:
            None: This method returns nothing.
        """
        cost_table = BrokerCostTable(logging.getLogger('example'))
        self.selector = RoundRobinSelector(cost_table)
        self.cache = CounterRedis()
        self.rotation = [
            'dhan',
            'fyers',
            'kotak',
            'zerodha',
        ]

    def run(self):
        """Prints the counter and the ranking for each order.

        Returns:
            None: This method returns nothing.
        """
        print(f'Selector: {RoundRobinSelector.NAME}')
        print(f'Counter key: {RoundRobinSelector.COUNTER_KEY}')
        print(f'Rotation: {self.rotation}')
        for order_number in range(1, 5):
            pipeline = self.cache.pipeline()
            commands_queued = self.selector.queue_redis_commands(pipeline, None, 'NSE:INFY')
            replies = pipeline.execute()
            ranked = self.selector.ranked_brokers(None, None, self.rotation, replies[:commands_queued])
            self.selector.record_passed_over(self.cache, 0)
            print(f'Order {order_number}: counter {replies[0]}, ranked {ranked}')


if __name__ == '__main__':
    TakingTurnsExample().run()
