"""Hands the mapping cache a Redis client the caller already holds, and drops it after a failure.

A `MappingRedisConnection` normally opens its own Redis client the first time `client()` is asked for one. A caller that already has a client, such as a test or a process with its own connection pool, can pass it in instead, and `client()` then returns that same object every time without opening anything.

This program passes a small stand-in client, which answers `ping` and nothing else, so no Redis server is needed. It then calls `forget()`, which is what the cache does after a Redis command fails. Notice that the next `client()` call answers None rather than trying again straight away: the connection waits `RETRY_SECONDS` before its next attempt, so a Redis that has gone away costs one failure a minute rather than one on every look-up.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisConnection/example_1_wrapping_a_client_you_already_have.py
"""

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisConnection,
)


class StandInClient:
    """A stand-in for a connected Redis client that only answers `ping`.

    Attributes:
        name (str): A label printed in place of the client's address.
    """

    def __init__(self, name):
        """Builds the stand-in with a label.

        Args:
            name (str): A label printed in place of the client's address.

        Returns:
            None: This method returns nothing.
        """
        self.name = name

    def ping(self):
        """Answers a ping as a connected Redis would.

        Returns:
            bool: Always True.
        """
        return True


class WrappingAClientExample:
    """Wraps a stand-in client in a mapping connection, then forgets it.

    Attributes:
        stand_in_client (StandInClient): The client the caller already holds.
        connection (MappingRedisConnection): The connection being shown.
    """

    def __init__(self):
        """Builds the connection around the stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.stand_in_client = StandInClient('the caller pool client')
        self.connection = MappingRedisConnection(self.stand_in_client)

    def run(self):
        """Asks for the client twice, forgets it, and asks again.

        Returns:
            None: This method returns nothing.
        """
        first = self.connection.client()
        second = self.connection.client()
        print(f'First client: {first.name}')
        print(f'Same object both times: {first is second}')
        print(f'Answers ping: {first.ping()}')
        print(f'Failed connections so far: {self.connection.failed_connections}')
        self.connection.forget()
        print('After forget(), a command failed and the client was dropped.')
        print(f'Client straight after forget(): {self.connection.client()}')
        print(f'Seconds before the next attempt: {MappingRedisConnection.RETRY_SECONDS}')
        print(f'Failed connections so far: {self.connection.failed_connections}')


if __name__ == '__main__':
    WrappingAClientExample().run()
