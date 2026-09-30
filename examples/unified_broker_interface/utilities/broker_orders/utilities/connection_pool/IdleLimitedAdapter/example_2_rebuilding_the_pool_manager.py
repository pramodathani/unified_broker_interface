"""Calls `init_poolmanager` on an adapter to rebuild its pool manager with a different size, and shows it still builds idle-limited pools.

requests calls `init_poolmanager` from the adapter's constructor, and again if the adapter is unpickled. `IdleLimitedAdapter` overrides it so that, whatever the size, the new pool manager builds `IdleLimitedHTTPConnectionPool` for `http` and `IdleLimitedHTTPSConnectionPool` for `https`, both carrying the adapter's idle limit and order.

The program rebuilds a Dhan-like adapter's pool manager with two pools of three connections each and looks at the pools it builds for an HTTPS and an HTTP address. Building a pool opens no connection, so nothing touches the network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedAdapter/example_2_rebuilding_the_pool_manager.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedAdapter,
)


class RebuildingThePoolManagerExample:
    """Rebuilds the pool manager and prints the pools it makes.

    Attributes:
        adapter (IdleLimitedAdapter): The adapter.
    """

    def __init__(self):
        """Builds an adapter with a 180 second limit that hands out the oldest connection first.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = IdleLimitedAdapter(180.0, 10, True)

    def run(self):
        """Rebuilds the pool manager and prints the pools for two addresses.

        Returns:
            None: This method returns nothing.
        """
        self.adapter.init_poolmanager(2, 3)
        addresses = [
            'https://api.dhan.co/',
            'http://127.0.0.1:8765/',
        ]
        for address in addresses:
            pool = self.adapter.poolmanager.connection_from_url(address)
            print(f'{address}: {type(pool).__name__}, idle limit {pool.maximum_idle_seconds} s, keeps {pool.pool.maxsize}, queue {type(pool.pool).__name__}')


if __name__ == '__main__':
    RebuildingThePoolManagerExample().run()
