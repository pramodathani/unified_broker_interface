"""Mounts an `IdleLimitedAdapter` on a requests session, as every broker order class does, and looks at the pool it builds for a broker host.

The adapter behaves like requests' default adapter except that its pools close a connection idle longer than a limit, keep a chosen number of connections per host, and can hand out the oldest connection first. `BrokerOrders` builds one per broker with that broker's `MAXIMUM_IDLE_SECONDS`, which for Zerodha is 300 seconds.

Asking the pool manager for a host's pool builds the pool but opens no connection, so the program runs offline. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedAdapter/example_1_mounted_on_a_session.py
"""

import requests

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedAdapter,
)


class MountedOnASessionExample:
    """Mounts the adapter and prints the pool for Kite's host.

    Attributes:
        adapter (IdleLimitedAdapter): The adapter.
        session (requests.Session): The session it is mounted on.
    """

    def __init__(self):
        """Builds the session with the adapter mounted for both schemes.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = IdleLimitedAdapter(300.0, 10, False)
        self.session = requests.Session()
        self.session.mount('https://', self.adapter)
        self.session.mount('http://', self.adapter)

    def run(self):
        """Prints the adapter's settings and the pool it builds.

        Returns:
            None: This method returns nothing.
        """
        chosen = self.session.get_adapter('https://api.kite.trade/orders/regular')
        print(f'Session uses our adapter: {chosen is self.adapter}')
        print(f'Adapter: idle limit {self.adapter.maximum_idle_seconds} s, {self.adapter.pool_size} connections, oldest first {self.adapter.oldest_first}')
        print(f'Retries: {self.adapter.max_retries.total}')
        pool = self.adapter.poolmanager.connection_from_url('https://api.kite.trade/')
        print(f'Pool for api.kite.trade: {type(pool).__name__}, idle limit {pool.maximum_idle_seconds} s, keeps {pool.pool.maxsize}')


if __name__ == '__main__':
    MountedOnASessionExample().run()
