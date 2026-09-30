"""Mounts a `HostnameCheckRelaxedAdapter` on a `requests` session and shows which requests it serves.

A `requests` session picks the transport adapter for each request by the longest URL prefix it has mounted. `build_session` in the Wisdom Capital instruments module mounts a `HostnameCheckRelaxedAdapter` for `https://`, so every HTTPS request the session sends goes through a pool whose TLS context skips the certificate's name check, while plain HTTP keeps the default adapter.

This program mounts the adapter the same way, after calling `init_poolmanager` to give it a pool of two connections, asks the session which adapter serves each of two URLs, and asks the adapter for the connection pool it would use for Wisdom Capital's instrument master. Making a pool opens no connection, so nothing reaches the network.

Notice that only the HTTPS URL gets the relaxed adapter, and that the pool for the market data host carries the relaxed settings.

Run it from the project root:

    python examples/stock_brokers/instruments/wisdom_capital/HostnameCheckRelaxedAdapter/example_2_mounted_on_a_session.py
"""

import requests

from stock_brokers.instruments.wisdom_capital import (
    INSTRUMENTS_URL,
    HostnameCheckRelaxedAdapter,
)


class MountedOnASessionExample:
    """Mounts the adapter on a session and prints which adapter and pool serve each URL.

    Attributes:
        adapter (HostnameCheckRelaxedAdapter): The adapter being shown.
        session (requests.Session): The session it is mounted on.
    """

    def __init__(self):
        """Builds the adapter with a pool of two connections and mounts it for HTTPS.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = HostnameCheckRelaxedAdapter()
        self.adapter.init_poolmanager(1, 2)
        self.session = requests.Session()
        self.session.mount('https://', self.adapter)

    def run(self):
        """Prints the adapter serving each URL and the settings of the pool for the instrument master.

        Returns:
            None: This method returns nothing.
        """
        for url in [
            INSTRUMENTS_URL,
            'http://example.com/',
        ]:
            print(f'{url} -> {type(self.session.get_adapter(url)).__name__}')
        pool = self.adapter.poolmanager.connection_from_url(INSTRUMENTS_URL)
        print(f'Pool for {pool.host}:{pool.port}')
        print(f'    assert_hostname: {pool.assert_hostname}')
        print(f'    check_hostname: {pool.conn_kw["ssl_context"].check_hostname}')
        print(f'    certificate verification: {pool.conn_kw["ssl_context"].verify_mode.name}')
        print(f'    connections kept: {pool.pool.maxsize}')


if __name__ == '__main__':
    MountedOnASessionExample().run()
