"""Writes a small broker selection algorithm by subclassing `BrokerSelector`, and runs it the way the order route does.

A selector only has to set `NAME` and implement `ranked_brokers`. Everything else it inherits from the base class: `queue_redis_commands` queues nothing and says so by returning 0, and `record_chosen`, `record_passed_over` and `record_outcome` accept what they are told and ignore it. This program writes a selector that offers every order to the brokers in alphabetical order, and then walks through one order the way the route does: queue the Redis commands, rank the rotation, offer the order down the ranking, and report back which broker took it.

The route would pass a Redis pipeline, a validated order and an instrument. The alphabetical selector reads none of them, so a small stand-in pipeline records any command it is given, which shows that the base class queues nothing, and the order and instrument are None. The broker cost table is built empty, which is how every process starts before it reads the database.

Notice that Dhan comes first because it sorts first, that the order moves on to Fyers when Dhan refuses it, and that the pipeline and the Redis stand-in are both still empty at the end.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/base/BrokerSelector/example_1_writing_a_selector.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.base import (
    BrokerSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)


class AlphabeticalSelector(BrokerSelector):
    """A selector that offers every order to the brokers in alphabetical order."""

    NAME = 'alphabetical'

    def ranked_brokers(self, order, instrument, rotation, redis_replies):
        """Sorts the rotation by broker name.

        Args:
            order (PlaceOrderRequest | None): The validated order, which this selector ignores.
            instrument (Instrument | None): The tradeable instrument, which this selector ignores.
            rotation (list): The broker names not excluded, in turn order.
            redis_replies (list): The replies to the queued commands, of which there are none.

        Returns:
            list: The broker names in alphabetical order.
        """
        del order
        del instrument
        del redis_replies
        return sorted(rotation)


class RecordingPipeline:
    """A stand-in for a Redis pipeline or client that records every command it is given.

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


class WritingASelectorExample:
    """Runs one order through the alphabetical selector.

    Attributes:
        selector (AlphabeticalSelector): The selector being shown.
        pipeline (RecordingPipeline): The stand-in pipeline the route would queue commands on.
        cache (RecordingPipeline): The stand-in Redis client the route would pass to `record_passed_over`.
        rotation (list): The broker names not excluded by configuration, in turn order.
        refusing_brokers (set): The brokers that pretend to refuse the order.
    """

    def __init__(self):
        """Builds the selector around an empty cost table.

        Returns:
            None: This method returns nothing.
        """
        cost_table = BrokerCostTable(logging.getLogger('example'))
        self.selector = AlphabeticalSelector(cost_table)
        self.pipeline = RecordingPipeline()
        self.cache = RecordingPipeline()
        self.rotation = [
            'zerodha',
            'kotak',
            'fyers',
            'dhan',
        ]
        self.refusing_brokers = {
            'dhan',
        }

    def run(self):
        """Ranks the rotation, offers the order down the ranking and reports the choice.

        Returns:
            None: This method returns nothing.
        """
        print(f'Selector: {self.selector.NAME}')
        print(f'Brokers in the cost table: {len(self.selector.cost_table.rows)}')
        commands_queued = self.selector.queue_redis_commands(self.pipeline, None, 'NSE:INFY')
        print(f'Redis commands queued: {commands_queued}')
        ranked = self.selector.ranked_brokers(None, None, self.rotation, [])
        print(f'Rotation: {self.rotation}')
        print(f'Ranked: {ranked}')
        passed_over = 0
        chosen = None
        for broker_name in ranked:
            if broker_name in self.refusing_brokers:
                print(f'{broker_name} refuses the order')
                passed_over += 1
                continue
            chosen = broker_name
            break
        print(f'Chosen: {chosen} after passing over {passed_over}')
        self.selector.record_chosen(chosen)
        self.selector.record_passed_over(self.cache, passed_over)
        self.selector.record_outcome(chosen, None)
        print(f'Commands on the pipeline: {self.pipeline.commands}')
        print(f'Commands sent to Redis afterwards: {self.cache.commands}')


if __name__ == '__main__':
    WritingASelectorExample().run()
