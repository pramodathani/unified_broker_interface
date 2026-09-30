"""Puts the preferred brokers at the front of the queue for an order.

A `FixedPrioritySelector` reads its preference from `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY` when it is built. This program sets that preference in the loaded configuration instead, so it runs without editing `.env`, and then asks the selector to rank the brokers that are not excluded.

The selector ignores the order and the instrument and reads nothing from Redis, so the program passes None for them and an empty list of Redis replies. It needs no data store, no network and no broker login.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/fixed_priority/FixedPrioritySelector/example_1_preferred_brokers_first.py
"""

import logging

from unified_broker_interface.utilities.broker_selection.fixed_priority import (
    FixedPrioritySelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
)
from utilities.configurations import api_configuration


class PreferredBrokersFirstExample:
    """Ranks one rotation of brokers with a configured preference and prints the result.

    Attributes:
        selector (FixedPrioritySelector): The selector being shown.
        rotation (list): The broker names not excluded by configuration, in turn order.
    """

    def __init__(self):
        """Builds the selector with Dhan preferred first and Zerodha second.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_priority'] = [
            'dhan',
            'zerodha',
        ]
        cost_table = BrokerCostTable(logging.getLogger('example'))
        self.selector = FixedPrioritySelector(cost_table)
        self.rotation = [
            'fyers',
            'zerodha',
            'kotak',
            'dhan',
            'shoonya',
        ]

    def run(self):
        """Prints the selector's name, its preference and the ranked brokers.

        Returns:
            None: This method returns nothing.
        """
        print(f'Selector: {FixedPrioritySelector.NAME}')
        print(f'Preference: {self.selector.priority}')
        print(f'Rotation: {self.rotation}')
        commands_queued = self.selector.queue_redis_commands(None, None, 'NSE:INFY')
        print(f'Redis commands queued: {commands_queued}')
        ranked = self.selector.ranked_brokers(None, None, self.rotation, [])
        print(f'Ranked: {ranked}')


if __name__ == '__main__':
    PreferredBrokersFirstExample().run()
