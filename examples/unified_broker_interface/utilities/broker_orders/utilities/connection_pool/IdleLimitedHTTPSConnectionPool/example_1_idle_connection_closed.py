"""Shows an HTTPS pool closing a connection that sat idle too long, instead of handing it to an order.

A broker's server closes a connection that has been idle for a while, often without the client noticing. An order sent on such a connection fails or waits for a timeout. `IdleLimitedHTTPSConnectionPool` notes when each connection is returned, and when it is taken again after more than `maximum_idle_seconds`, closes it first, so the request opens a fresh connection rather than trusting a stale one.

urllib3 takes a connection with `_get_conn` and returns it with `_put_conn` around every request; the program calls those two directly, because sending a real request would need the network. The pool's `ConnectionCls` is replaced with a stand-in connection that never opens a socket and records when it is closed. The limit is 0.05 seconds and the program waits 0.1 seconds, so the second connection is always past it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedHTTPSConnectionPool/example_1_idle_connection_closed.py
"""

import time

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedHTTPSConnectionPool,
)


class RecordingConnection:
    """A stand-in for `urllib3.connection.HTTPSConnection` that never opens a socket and records when it is closed.

    Attributes:
        created (int): How many connections have been built, for naming them.
        name (str): The connection's name.
        is_connected (bool): Always True, so urllib3 treats it as a live connection.
        closed_count (int): How many times it was closed.
    """

    created = 0

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
        RecordingConnection.created = RecordingConnection.created + 1
        self.name = f'connection {RecordingConnection.created} to {host}'
        self.is_connected = True
        self.closed_count = 0

    def close(self):
        """Records that the connection was closed.

        Returns:
            None: This method returns nothing.
        """
        self.closed_count = self.closed_count + 1


class IdleConnectionClosedExample:
    """Takes and returns connections with and without a long idle gap.

    Attributes:
        pool (IdleLimitedHTTPSConnectionPool): The pool being shown.
    """

    def __init__(self):
        """Builds a pool for Kite's host with a 0.05 second idle limit.

        Returns:
            None: This method returns nothing.
        """
        self.pool = IdleLimitedHTTPSConnectionPool(
            'api.kite.trade',
            443,
            maximum_idle_seconds=0.05,
        )
        self.pool.ConnectionCls = RecordingConnection

    def run(self):
        """Reuses a connection straight away, then again after an idle gap.

        Returns:
            None: This method returns nothing.
        """
        print(f'Idle limit: {self.pool.maximum_idle_seconds} seconds')
        connection = self.pool._get_conn()
        print(f'Took a new {connection.name}')
        self.pool._put_conn(connection)
        again = self.pool._get_conn()
        print(f'Taken straight back: {again.name}, closed {again.closed_count} times')
        self.pool._put_conn(again)
        time.sleep(0.1)
        after_gap = self.pool._get_conn()
        print(f'Taken after 0.1 seconds idle: {after_gap.name}, closed {after_gap.closed_count} times, so the next request reconnects')


if __name__ == '__main__':
    IdleConnectionClosedExample().run()
