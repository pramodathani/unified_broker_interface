"""Shows that a Redis nobody can reach gives back None quickly instead of raising.

When a `MappingRedisConnection` is built without a client, `client()` opens one from `redis_configuration` and pings it. The client has redis-py's retry switched off and short timeouts, so a refused port is noticed in well under a second, the failure is counted in `failed_connections`, and `client()` answers None. Every caller of the mapping cache checks for None and treats it as a cache miss, so an order still resolves through Postgres.

This program points `redis_configuration` at port 9 on this machine, where nothing listens, so it never touches a real Redis wherever it is run. Notice that the second call within the retry window answers None without a second attempt, because the failure is remembered for `RETRY_SECONDS`, and that the three timeout settings are the ones the class declares.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisConnection/example_2_unreachable_redis_is_a_miss.py
"""

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisConnection,
)
from utilities.configurations import redis_configuration


class UnreachableRedisExample:
    """Asks for a client from a Redis address where nothing listens.

    Attributes:
        connection (MappingRedisConnection): The connection being shown.
    """

    def __init__(self):
        """Points the Redis configuration at a closed port and builds the connection.

        Returns:
            None: This method returns nothing.
        """
        redis_configuration['host'] = '127.0.0.1'
        redis_configuration['port'] = 9
        self.connection = MappingRedisConnection()

    def run(self):
        """Asks for the client twice and prints what came back and what was counted.

        Returns:
            None: This method returns nothing.
        """
        print(f'Connect timeout: {MappingRedisConnection.CONNECT_TIMEOUT_SECONDS} seconds')
        print(f'Command timeout: {MappingRedisConnection.SOCKET_TIMEOUT_SECONDS} seconds')
        print(f'Retry window: {MappingRedisConnection.RETRY_SECONDS} seconds')
        first = self.connection.client()
        print(f'First attempt: {first}')
        print(f'Failed connections: {self.connection.failed_connections}')
        second = self.connection.client()
        print(f'Second attempt inside the retry window: {second}')
        print(f'Failed connections: {self.connection.failed_connections}')
        self.connection.forget()
        print(f'After forget(): {self.connection.client()}')
        print(f'Failed connections: {self.connection.failed_connections}')


if __name__ == '__main__':
    UnreachableRedisExample().run()
