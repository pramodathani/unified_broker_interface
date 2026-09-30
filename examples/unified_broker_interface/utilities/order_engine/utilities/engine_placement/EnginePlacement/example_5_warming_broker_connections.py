"""Starts the background threads that keep order connections to the brokers warm, so an order does not pay for a new TLS handshake.

When the order engine starts it calls `start_connection_warmers`. For each broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` it starts a `ConnectionWarmer`, a daemon thread that sends a credential-free `HEAD` request through that broker's order connection pool about once a minute per connection. A name that is not a broker is logged and ignored, because warming only saves time and must never stop the engine.

This program names Zerodha and a broker the engine does not know. So that nothing reaches Kite, Zerodha's `warm_connection` is replaced by `PingCounter.warm_connection`, a stand-in that only counts the ping and signals that one arrived. The program waits for the first ping, then stops the warmer the way the engine does when it shuts down. The number of pings depends on how fast the thread runs, so the program prints only that one arrived.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/EnginePlacement/example_5_warming_broker_connections.py
"""

import logging
import threading

from test_runs.redis_stand_ins import FakeRedis
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from utilities.configurations import api_configuration


class PingCounter:
    """A stand-in for a broker's `warm_connection` that counts pings instead of sending them.

    Attributes:
        pings (int): How many pings arrived.
        first_ping (threading.Event): Set when the first ping arrives.
    """

    def __init__(self):
        """Builds the counter with no pings.

        Returns:
            None: This method returns nothing.
        """
        self.pings = 0
        self.first_ping = threading.Event()

    def warm_connection(self):
        """Counts one ping.

        Returns:
            str: `kept`, as when a healthy connection went back to the pool.
        """
        self.pings = self.pings + 1
        self.first_ping.set()
        return 'kept'


class WarmingBrokerConnectionsExample:
    """Starts the configured warmers with Zerodha's ping replaced, waits for a ping and stops them.

    Attributes:
        placement (EnginePlacement): The placement being shown.
        ping_counter (PingCounter): The stand-in for Zerodha's ping.
    """

    def __init__(self):
        """Names the brokers to warm and builds the placement with Zerodha's ping replaced.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_warm_brokers'] = [
            'zerodha',
            'sharekhan',
        ]
        self.placement = EnginePlacement(FakeRedis(), logging.getLogger('example'))
        self.ping_counter = PingCounter()
        zerodha_orders = self.placement.order_placement.broker_orders['zerodha']
        zerodha_orders.warm_connection = self.ping_counter.warm_connection

    def run(self):
        """Starts the warmers, waits for the first ping and stops them.

        Returns:
            None: This method returns nothing.
        """
        self.placement.start_connection_warmers()
        warmers = self.placement.order_placement.connection_warmers
        warmed_brokers = []
        for warmer in warmers:
            warmed_brokers.append(warmer.broker_orders.BROKER_NAME)
        print(f'warmers started for: {warmed_brokers}')
        arrived = self.ping_counter.first_ping.wait(5.0)
        print(f'a ping reached the stand-in: {arrived}')
        for warmer in warmers:
            print(f'{warmer.broker_orders.BROKER_NAME} warmer running: {warmer.is_running()}, failing: {warmer.failing}')
            warmer.stop()
            print(f'{warmer.broker_orders.BROKER_NAME} warmer running after stop: {warmer.is_running()}')


if __name__ == '__main__':
    WarmingBrokerConnectionsExample().run()
