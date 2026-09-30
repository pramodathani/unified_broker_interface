"""Builds a `HostnameCheckRelaxedAdapter` and reads the TLS settings of the connection pool it makes.

Wisdom Capital's market data host serves a certificate issued to a different domain, so an ordinary `requests` session refuses it on the name check alone. `HostnameCheckRelaxedAdapter` is a `requests` transport adapter whose `init_poolmanager` builds the connection pool with a TLS context that still requires a certificate chaining to a trusted authority and still in date, but skips the check that the certificate's name matches the host.

`requests` calls `init_poolmanager` from the adapter's constructor. The program also calls it again with its own pool sizes, as `requests` does when an adapter is rebuilt, and prints the settings the pool manager was given each time. Nothing connects to anything.

Notice that certificate verification stays `CERT_REQUIRED` while `check_hostname` and `assert_hostname` are both off, and that the second call keeps those settings while changing the pool sizes.

Run it from the project root:

    python examples/stock_brokers/instruments/wisdom_capital/HostnameCheckRelaxedAdapter/example_1_a_pool_that_skips_the_name_check.py
"""

from stock_brokers.instruments.wisdom_capital import (
    HostnameCheckRelaxedAdapter,
)


class APoolThatSkipsTheNameCheckExample:
    """Builds the adapter, rebuilds its pool manager and prints the pool settings each time.

    Attributes:
        adapter (HostnameCheckRelaxedAdapter): The adapter being shown.
    """

    def __init__(self):
        """Builds the adapter, which builds its first pool manager.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = HostnameCheckRelaxedAdapter()

    def show(self, heading):
        """Prints the settings the adapter's pool manager hands to every pool it makes.

        Args:
            heading (str): What the settings follow from.

        Returns:
            None: This method returns nothing.
        """
        pool_settings = self.adapter.poolmanager.connection_pool_kw
        context = pool_settings['ssl_context']
        print(heading)
        print(f'    certificate verification: {context.verify_mode.name}')
        print(f'    check_hostname: {context.check_hostname}')
        print(f'    assert_hostname: {pool_settings["assert_hostname"]}')
        print(f'    maxsize: {pool_settings["maxsize"]}, block: {pool_settings["block"]}')

    def run(self):
        """Prints the pool settings, rebuilds the pool manager with other sizes and prints them again.

        Returns:
            None: This method returns nothing.
        """
        self.show('After construction:')
        self.adapter.init_poolmanager(4, 8, block=True)
        self.show('After init_poolmanager(4, 8, block=True):')


if __name__ == '__main__':
    APoolThatSkipsTheNameCheckExample().run()
