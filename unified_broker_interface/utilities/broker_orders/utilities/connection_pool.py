"""Connection pools that never hand an order a connection that has been idle long enough for the broker to have closed it."""

import functools
import threading
import time
import weakref

from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.connectionpool import HTTPSConnectionPool


class IdleLimitedHTTPSConnectionPool(HTTPSConnectionPool):
    """An HTTPS pool that closes a pooled connection instead of reusing it once it has been idle longer than a limit.

    A closed connection object is still handed out, and opens a new connection when a request is sent on it, exactly as urllib3 does with a connection it finds dropped.

    Attributes:
        maximum_idle_seconds (float): How long a connection may sit in the pool and still be reused.
        idle_lock (threading.Lock): Guards `returned_at`, as a worker's threads share the pool.
        returned_at (weakref.WeakKeyDictionary): Each pooled connection to the `time.monotonic()` it was returned at.
    """

    def __init__(
        self,
        host,
        port=None,
        maximum_idle_seconds=None,
        **keyword_arguments,
    ):
        """Builds the pool.

        Args:
            host (str): The host.
            port (int | None): The port.
            maximum_idle_seconds (float | None): How long a connection may sit idle and still be reused; None never refuses one.
            **keyword_arguments (object): The remaining urllib3 pool arguments.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(host, port, **keyword_arguments)
        self.maximum_idle_seconds = maximum_idle_seconds
        self.idle_lock = threading.Lock()
        self.returned_at = weakref.WeakKeyDictionary()

    def _get_conn(self, timeout=None):
        """Takes a connection from the pool, closing it first when it has been idle too long.

        Args:
            timeout (float | None): How long to wait for a connection when the pool blocks.

        Returns:
            urllib3.connection.HTTPSConnection: The connection.
        """
        connection = super()._get_conn(timeout)
        with self.idle_lock:
            returned_at = self.returned_at.pop(connection, None)
        if returned_at is None or self.maximum_idle_seconds is None:
            return connection
        if time.monotonic() - returned_at > self.maximum_idle_seconds:
            connection.close()
        return connection

    def _put_conn(self, conn):
        """Returns a connection to the pool, noting when.

        Args:
            conn (urllib3.connection.HTTPSConnection | None): The connection.

        Returns:
            None: This method returns nothing.
        """
        if conn is not None:
            with self.idle_lock:
                self.returned_at[conn] = time.monotonic()
        super()._put_conn(conn)


class IdleLimitedHTTPConnectionPool(HTTPConnectionPool):
    """An HTTP pool that closes a pooled connection instead of reusing it once it has been idle longer than a limit; the plain HTTP twin of `IdleLimitedHTTPSConnectionPool`, used by the offline tests.

    Attributes:
        maximum_idle_seconds (float): How long a connection may sit in the pool and still be reused.
        idle_lock (threading.Lock): Guards `returned_at`, as a worker's threads share the pool.
        returned_at (weakref.WeakKeyDictionary): Each pooled connection to the `time.monotonic()` it was returned at.
    """

    def __init__(
        self,
        host,
        port=None,
        maximum_idle_seconds=None,
        **keyword_arguments,
    ):
        """Builds the pool.

        Args:
            host (str): The host.
            port (int | None): The port.
            maximum_idle_seconds (float | None): How long a connection may sit idle and still be reused; None never refuses one.
            **keyword_arguments (object): The remaining urllib3 pool arguments.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(host, port, **keyword_arguments)
        self.maximum_idle_seconds = maximum_idle_seconds
        self.idle_lock = threading.Lock()
        self.returned_at = weakref.WeakKeyDictionary()

    def _get_conn(self, timeout=None):
        """Takes a connection from the pool, closing it first when it has been idle too long.

        Args:
            timeout (float | None): How long to wait for a connection when the pool blocks.

        Returns:
            urllib3.connection.HTTPConnection: The connection.
        """
        connection = super()._get_conn(timeout)
        with self.idle_lock:
            returned_at = self.returned_at.pop(connection, None)
        if returned_at is None or self.maximum_idle_seconds is None:
            return connection
        if time.monotonic() - returned_at > self.maximum_idle_seconds:
            connection.close()
        return connection

    def _put_conn(self, conn):
        """Returns a connection to the pool, noting when.

        Args:
            conn (urllib3.connection.HTTPConnection | None): The connection.

        Returns:
            None: This method returns nothing.
        """
        if conn is not None:
            with self.idle_lock:
                self.returned_at[conn] = time.monotonic()
        super()._put_conn(conn)


class IdleLimitedAdapter(HTTPAdapter):
    """A requests adapter whose pools refuse connections idle longer than a limit, and which otherwise behaves as requests' default adapter.

    Attributes:
        maximum_idle_seconds (float | None): How long a pooled connection may sit idle and still be reused.
    """

    def __init__(self, maximum_idle_seconds):
        """Builds the adapter with requests' default pool sizes and no retries.

        Args:
            maximum_idle_seconds (float | None): How long a pooled connection may sit idle and still be reused.

        Returns:
            None: This method returns nothing.
        """
        self.maximum_idle_seconds = maximum_idle_seconds
        super().__init__()

    def init_poolmanager(
        self,
        connections,
        maxsize,
        block=False,
        **pool_keyword_arguments,
    ):
        """Builds requests' pool manager, then makes it create idle-limited pools.

        Args:
            connections (int): How many pools to keep.
            maxsize (int): How many connections each pool keeps.
            block (bool): Whether a pool blocks when it has no free connection.
            **pool_keyword_arguments (object): The remaining pool manager arguments.

        Returns:
            None: This method returns nothing.
        """
        super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            **pool_keyword_arguments,
        )
        self.poolmanager.pool_classes_by_scheme = {
            'http': functools.partial(
                IdleLimitedHTTPConnectionPool,
                maximum_idle_seconds=self.maximum_idle_seconds,
            ),
            'https': functools.partial(
                IdleLimitedHTTPSConnectionPool,
                maximum_idle_seconds=self.maximum_idle_seconds,
            ),
        }
