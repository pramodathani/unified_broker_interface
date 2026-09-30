"""Shows what happens when a preferred broker is not in the rotation, and walks down the ranking until one broker takes the order.

A broker named in the preference but excluded by `UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` never appears in the ranking, because the selector only ranks the rotation it is given. The route then offers the order to each ranked broker in turn, and the first that can take it gets it.

This program pretends that Zerodha is excluded today and that Dhan refuses the order. It then reports the chosen broker to `record_chosen`, `record_passed_over` and `record_outcome`, which this selector accepts and ignores, so it behaves the same on every order. A small stand-in replaces the Redis client, and it records any command it is given, which shows that the selector sends none.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/fixed_priority/FixedPrioritySelector/example_2_preferred_broker_excluded.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.fixed_priority import (
    FixedPrioritySelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)
from utilities.configurations import api_configuration


class RecordingRedis:
    """A stand-in for the Redis client that records every command it is sent.

    Attributes:
        commands (list): The commands received, as (name, arguments) pairs.
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
            int: Always the amount, as if the key had been zero.
        """
        self.commands.append(('incrby', key, amount))
        return amount


class PreferredBrokerExcludedExample:
    """Ranks a rotation that lacks one preferred broker, then offers the order down the ranking.

    Attributes:
        selector (FixedPrioritySelector): The selector being shown.
        rotation (list): The broker names not excluded by configuration, in turn order.
        refusing_brokers (set): The brokers that pretend to refuse the order.
        cache (RecordingRedis): The stand-in Redis client.
    """

    def __init__(self):
        """Builds the selector with Zerodha, then Dhan, then Fyers preferred.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_priority'] = [
            'zerodha',
            'dhan',
            'fyers',
        ]
        cost_table = BrokerCostTable(logging.getLogger('example'))
        self.selector = FixedPrioritySelector(cost_table)
        self.rotation = [
            'kotak',
            'fyers',
            'dhan',
            'groww',
        ]
        self.refusing_brokers = {
            'dhan',
        }
        self.cache = RecordingRedis()

    def run(self):
        """Prints the ranking and which broker ends up with the order.

        Returns:
            None: This method returns nothing.
        """
        ranked = self.selector.ranked_brokers(None, None, self.rotation, [])
        print(f'Preference: {self.selector.priority}')
        print(f'Rotation without zerodha: {self.rotation}')
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
        print(f'Redis commands sent by the selector: {self.cache.commands}')


if __name__ == '__main__':
    PreferredBrokerExcludedExample().run()
