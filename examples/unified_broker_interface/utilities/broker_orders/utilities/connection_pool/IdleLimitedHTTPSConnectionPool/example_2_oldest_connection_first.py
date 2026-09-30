"""Compares the order in which a default pool and an `oldest_first` pool hand out their connections.

urllib3 hands out the connection returned most recently, which keeps one connection hot and lets the rest go stale. A warmer that pings one connection at a time would then ping the same one forever. A pool built with `oldest_first` hands out the connection returned longest ago, so single pings rotate through every connection in the pool.

The program fills each pool with three stand-in connections, returned in the order 1, 2, 3, then takes three and prints which came out. The stand-in never opens a socket. `_get_conn` and `_put_conn` are what urllib3 calls around every request; they are called directly here because sending would need the network. No idle limit is set, so nothing is closed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_pool/IdleLimitedHTTPSConnectionPool/example_2_oldest_connection_first.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedHTTPSConnectionPool,
)


class NamedConnection:
    """A stand-in for `urllib3.connection.HTTPSConnection` that never opens a socket.

    Attributes:
        created (int): How many connections have been built, for naming them.
        number (int): The connection's number.
        is_connected (bool): Always True, so urllib3 treats it as a live connection.
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
        NamedConnection.created = NamedConnection.created + 1
        self.number = NamedConnection.created
        self.is_connected = True

    def close(self):
        """Does nothing, as the stand-in holds no socket.

        Returns:
            None: This method returns nothing.
        """
        return None


class OldestConnectionFirstExample:
    """Fills two pools the same way and prints the order each hands connections out."""

    def handed_out_order(self, oldest_first):
        """Fills one pool with three connections and takes them back out.

        Args:
            oldest_first (bool): Whether the pool hands out the oldest connection first.

        Returns:
            list: The connection numbers in the order they were handed out.
        """
        NamedConnection.created = 0
        pool = IdleLimitedHTTPSConnectionPool(
            'api.dhan.co',
            443,
            oldest_first=oldest_first,
            maxsize=3,
        )
        pool.ConnectionCls = NamedConnection
        taken = []
        for _ in range(3):
            taken.append(pool._get_conn())
        for connection in taken:
            pool._put_conn(connection)
        handed_out = []
        for _ in range(3):
            handed_out.append(pool._get_conn().number)
        return handed_out

    def run(self):
        """Prints the order for both pools.

        Returns:
            None: This method returns nothing.
        """
        print('Returned in the order [1, 2, 3]')
        print(f'Default pool hands out: {self.handed_out_order(False)}')
        print(f'oldest_first pool hands out: {self.handed_out_order(True)}')


if __name__ == '__main__':
    OldestConnectionFirstExample().run()
