"""Shows how the turn moves past a broker that cannot take orders, so the broker after it does not get two turns in a row.

When the broker whose turn it is cannot take an order, the route offers it to the next broker in the ranking. It then calls `record_passed_over` with the number of brokers it skipped, and a `RoundRobinSelector` adds that number to the counter in Redis. The next order therefore starts after the broker that took this one. Without that step, the broker after an unable one would take its own turn as well as the unable broker's.

This program pretends that Groww takes no orders at all, as in the after-market session, and places three orders. A stand-in Redis keeps the counter in a dictionary and records every command, and a stand-in pipeline applies the queued increment when executed.

Notice that the first order skips Groww and goes to INDmoney, that the selector then sends one `INCRBY` of 1, and that the second order starts at Kotak, after INDmoney, instead of giving INDmoney a second turn. Orders that pass over nobody send no `INCRBY` at all.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/round_robin/RoundRobinSelector/example_2_skipping_a_refusing_broker.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.round_robin import (
    RoundRobinSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)


class CounterRedis:
    """A stand-in for the Redis client that keeps integer keys in a dictionary and records `INCRBY` commands.

    Attributes:
        values (dict): The value (int) of each key.
        commands (list): Every `INCRBY` sent directly, as tuples of name, key and amount.
    """

    def __init__(self):
        """Builds the stand-in with no keys.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}
        self.commands = []

    def incrby(self, key, amount):
        """Adds to a key, as Redis `INCRBY` does, and records the command.

        Args:
            key (str): The key.
            amount (int): How much to add.

        Returns:
            int: The key's new value.
        """
        self.commands.append((
            'incrby',
            key,
            amount,
        ))
        return self.add(key, amount)

    def add(self, key, amount):
        """Adds to a key without recording a command.

        Args:
            key (str): The key.
            amount (int): How much to add.

        Returns:
            int: The key's new value.
        """
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]


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
            replies.append(self.cache.add(key, 1))
        self.queued = []
        return replies


class SkippingARefusingBrokerExample:
    """Places three orders while one broker refuses every order.

    Attributes:
        selector (RoundRobinSelector): The selector being shown.
        cache (CounterRedis): The stand-in Redis client.
        rotation (list): The broker names not excluded by configuration, in turn order.
        refusing_brokers (set): The brokers that refuse every order.
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
            'groww',
            'indmoney',
            'kotak',
        ]
        self.refusing_brokers = {
            'groww',
        }

    def place_one(self, order_number):
        """Ranks the rotation for one order, offers it down the ranking and moves the turn on.

        Args:
            order_number (int): The order's number, for the printout.

        Returns:
            None: This method returns nothing.
        """
        pipeline = CounterPipeline(self.cache)
        self.selector.queue_redis_commands(pipeline, None, 'NSE:INFY')
        replies = pipeline.execute()
        ranked = self.selector.ranked_brokers(None, None, self.rotation, replies)
        passed_over = 0
        chosen = None
        for broker_name in ranked:
            if broker_name in self.refusing_brokers:
                passed_over += 1
                continue
            chosen = broker_name
            break
        self.selector.record_passed_over(self.cache, passed_over)
        counter = self.cache.values[RoundRobinSelector.COUNTER_KEY]
        print(f'Order {order_number}: ranked {ranked}')
        print(f'  chosen {chosen} after passing over {passed_over}; counter now {counter}')

    def run(self):
        """Places three orders and prints the direct Redis commands the selector sent.

        Returns:
            None: This method returns nothing.
        """
        print(f'Rotation: {self.rotation}')
        print(f'Refusing: {sorted(self.refusing_brokers)}')
        for order_number in range(1, 4):
            self.place_one(order_number)
        print(f'INCRBY commands sent by record_passed_over: {self.cache.commands}')


if __name__ == '__main__':
    SkippingARefusingBrokerExample().run()
