"""Shows the adapter building an `IdleLimitedHTTPConnectionPool` for a plain HTTP address, with the adapter's own limit and order.

Code never builds the pool itself in normal use. A broker order class mounts an `IdleLimitedAdapter` on its session, and the adapter's pool manager builds one pool per host the first time a URL for that host is used. For an `http://` address that is this class, carrying the adapter's idle limit and `oldest_first` setting, which is how the offline tests reach it with a local server.

Building the pool opens no connection, so the program only asks the pool manager for the pool of a local address and prints what it holds. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedHTTPConnectionPool/example_2_built_by_the_adapter.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedAdapter,
)
from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedHTTPConnectionPool,
)


class BuiltByTheAdapterExample:
    """Asks an adapter for the pool of a local address and prints it.

    Attributes:
        adapter (IdleLimitedAdapter): The adapter that builds the pool.
    """

    def __init__(self):
        """Builds an adapter with a 30 second limit, four connections and oldest-first order.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = IdleLimitedAdapter(30.0, 4, True)

    def run(self):
        """Prints the pool the adapter builds for a local address.

        Returns:
            None: This method returns nothing.
        """
        pool = self.adapter.poolmanager.connection_from_url('http://127.0.0.1:8765/')
        print(f'Pool class: {type(pool).__name__}')
        print(f'Is an IdleLimitedHTTPConnectionPool: {isinstance(pool, IdleLimitedHTTPConnectionPool)}')
        print(f'Host: {pool.host}:{pool.port}')
        print(f'Idle limit: {pool.maximum_idle_seconds} seconds')
        print(f'Connections kept: {pool.pool.maxsize}')
        print(f'Hands out the oldest first: {type(pool.pool).__name__ == "Queue"}')
        print(f'Connections remembered as returned: {len(pool.returned_at)}')


if __name__ == '__main__':
    BuiltByTheAdapterExample().run()
