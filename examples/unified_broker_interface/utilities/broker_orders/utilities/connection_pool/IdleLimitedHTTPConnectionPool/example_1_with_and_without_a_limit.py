"""Compares a plain HTTP pool with an idle limit and one without, after the same idle gap.

`IdleLimitedHTTPConnectionPool` is the plain HTTP twin of the HTTPS pool the brokers use, and the offline tests run against it with a local server. A pool built with an idle limit closes a connection taken after a longer gap; a pool built with `maximum_idle_seconds=None` never does, which is urllib3's own behaviour.

urllib3 takes a connection with `_get_conn` and returns it with `_put_conn` around every request; the program calls those two directly, because sending would need a server. The pool's `ConnectionCls` is replaced with a stand-in that never opens a socket and counts how often it is closed. The gap is 0.1 seconds against a 0.05 second limit, so the result is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedHTTPConnectionPool/example_1_with_and_without_a_limit.py
"""

import time

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedHTTPConnectionPool,
)


class CountingConnection:
    """A stand-in for `urllib3.connection.HTTPConnection` that never opens a socket and counts closes.

    Attributes:
        is_connected (bool): Always True, so urllib3 treats it as a live connection.
        closed_count (int): How many times it was closed.
    """

    def __init__(self, host, port, timeout, **keyword_arguments):
        """Builds the connection.

        Args:
            host (str): The host.
            port (int | None): The port.
            timeout (object): The connect timeout.
            **keyword_arguments (object): The remaining connection arguments.

        Returns:
            None: This method returns nothing.
        """
        self.is_connected = True
        self.closed_count = 0

    def close(self):
        """Counts the close.

        Returns:
            None: This method returns nothing.
        """
        self.closed_count = self.closed_count + 1


class WithAndWithoutALimitExample:
    """Runs the same idle gap through two pools."""

    def closes_after_gap(self, maximum_idle_seconds):
        """Returns a connection, waits, takes it again and reports how often it was closed.

        Args:
            maximum_idle_seconds (float | None): The pool's idle limit.

        Returns:
            int: How many times the connection was closed.
        """
        pool = IdleLimitedHTTPConnectionPool(
            '127.0.0.1',
            8080,
            maximum_idle_seconds=maximum_idle_seconds,
        )
        pool.ConnectionCls = CountingConnection
        connection = pool._get_conn()
        pool._put_conn(connection)
        time.sleep(0.1)
        return pool._get_conn().closed_count

    def run(self):
        """Prints the result for both pools.

        Returns:
            None: This method returns nothing.
        """
        print(f'Limit 0.05 seconds: closed {self.closes_after_gap(0.05)} times after a 0.1 second gap')
        print(f'No limit: closed {self.closes_after_gap(None)} times after a 0.1 second gap')


if __name__ == '__main__':
    WithAndWithoutALimitExample().run()
