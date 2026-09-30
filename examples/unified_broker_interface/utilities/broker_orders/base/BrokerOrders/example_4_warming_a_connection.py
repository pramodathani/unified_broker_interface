"""Sends warming pings through `BrokerOrders.warm_connection` to a stand-in adapter backed by a local socket pair, and shows when a connection is kept or discarded.

A warming ping is a `HEAD` request with no credentials to the broker's host. `warm_url` picks the host: the one the latest order request went to, which `remember_origin` records, or the class's `WARM_URL` before there has been one. After the answer, the connection is watched for `WARM_SETTLE_SECONDS`; it goes back to the pool only if the server stayed silent, because a server that closes a connection straight after answering would otherwise hand a dead connection to the next order.

Nothing reaches a broker. The order class's `adapter` is replaced with a stand-in whose `send` records the request and returns a response whose connection is one end of `socket.socketpair()`, a pair of connected sockets inside this process. Writing a byte into the other end plays the part of a server that talks after answering. `WARM_SETTLE_SECONDS` is set to 0.05 on the instance so the program is quick.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/base/BrokerOrders/example_4_warming_a_connection.py
"""

import socket

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders


class ExampleBrokerOrders(BrokerOrders):
    """A made-up broker with a public warming URL."""

    BROKER_NAME = 'example_broker'
    WARM_URL = 'https://api.example-broker.in/'


class SocketConnection:
    """A stand-in for a pooled urllib3 connection, holding one end of a socket pair.

    Attributes:
        sock (socket.socket): The socket.
        closed (bool): Whether the connection was closed.
    """

    def __init__(self, sock):
        """Builds the connection.

        Args:
            sock (socket.socket): The socket.

        Returns:
            None: This method returns nothing.
        """
        self.sock = sock
        self.closed = False

    def close(self):
        """Records that the connection was closed.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True


class RawResponse:
    """A stand-in for a urllib3 response.

    Attributes:
        connection (SocketConnection): The connection the answer came on.
        released (bool): Whether the connection was handed back to the pool.
    """

    def __init__(self, connection):
        """Builds the response.

        Args:
            connection (SocketConnection): The connection.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.released = False

    def read(self):
        """Reads the empty body of a `HEAD` answer.

        Returns:
            bytes: Always empty.
        """
        return b''

    def release_conn(self):
        """Records that the connection was handed back.

        Returns:
            None: This method returns nothing.
        """
        self.released = True


class StandInResponse:
    """A stand-in for a `requests.Response` carrying only its raw response.

    Attributes:
        raw (RawResponse): The raw response.
    """

    def __init__(self, raw):
        """Builds the response.

        Args:
            raw (RawResponse): The raw response.

        Returns:
            None: This method returns nothing.
        """
        self.raw = raw


class SocketPairAdapter:
    """A stand-in for `IdleLimitedAdapter` whose every answer arrives on one end of a local socket pair.

    Attributes:
        client_socket (socket.socket): The end the order class watches.
        server_socket (socket.socket): The end that plays the broker's server.
        pinged (list): Each ping's method and URL.
        last_raw (RawResponse | None): The latest raw response handed out.
    """

    def __init__(self):
        """Opens the socket pair.

        Returns:
            None: This method returns nothing.
        """
        self.client_socket, self.server_socket = socket.socketpair()
        self.pinged = []
        self.last_raw = None

    def send(self, prepared_request, **keyword_arguments):
        """Records the ping and answers on the socket pair.

        Args:
            prepared_request (requests.PreparedRequest): The ping.
            **keyword_arguments (object): The stream, timeout and certificate settings.

        Returns:
            StandInResponse: The response.
        """
        self.pinged.append(f'{prepared_request.method} {prepared_request.url}')
        self.last_raw = RawResponse(SocketConnection(self.client_socket))
        return StandInResponse(self.last_raw)

    def close(self):
        """Closes both sockets.

        Returns:
            None: This method returns nothing.
        """
        self.client_socket.close()
        self.server_socket.close()


class WarmingAConnectionExample:
    """Pings a quiet server, then a talkative one, then with no URL at all.

    Attributes:
        broker_orders (ExampleBrokerOrders): The broker's order class.
        adapter (SocketPairAdapter): The stand-in adapter.
    """

    def __init__(self):
        """Builds the order class and swaps in the stand-in adapter.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleBrokerOrders()
        self.broker_orders.WARM_SETTLE_SECONDS = 0.05
        self.adapter = SocketPairAdapter()
        self.broker_orders.adapter = self.adapter

    def ping(self, label):
        """Sends one ping and prints what happened to its connection.

        Args:
            label (str): What the server does.

        Returns:
            None: This method returns nothing.
        """
        result = self.broker_orders.warm_connection()
        raw = self.adapter.last_raw
        print(f'{label}: {result}; connection closed {raw.connection.closed}, handed back {raw.released}')

    def run(self):
        """Pings twice, remembers an order's host, and pings a broker with nothing to warm.

        Returns:
            None: This method returns nothing.
        """
        print(f'URL before any order: {self.broker_orders.warm_url()}')
        self.ping('Quiet server')
        self.broker_orders.remember_origin('https://api-2.example-broker.in/orders/regular?x=1')
        print(f'URL after an order: {self.broker_orders.warm_url()}')
        self.adapter.server_socket.sendall(b'x')
        self.ping('Server talks after answering')
        print(f'Pings sent: {self.adapter.pinged}')
        self.adapter.close()
        nothing_to_warm = BrokerOrders()
        print(f'A broker with no WARM_URL and no orders yet: {nothing_to_warm.warm_connection()}')


if __name__ == '__main__':
    WarmingAConnectionExample().run()
