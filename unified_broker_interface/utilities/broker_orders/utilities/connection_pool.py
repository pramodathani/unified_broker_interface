"""Connection pools that never hand an order a connection that has been idle long enough for the broker to have closed it."""

import functools
import queue
import threading
import time
import weakref

from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.connectionpool import HTTPSConnectionPool

DEFAULT_POOL_SIZE = 10


class IdleLimitedHTTPSConnectionPool(HTTPSConnectionPool):
    """An HTTPS pool that closes a pooled connection instead of reusing it once it has been idle longer than a limit, and can hand out the connection that has waited longest.

    A closed connection object is still handed out, and opens a new connection when a request is sent on it, exactly as urllib3 does with a connection it finds dropped.

    urllib3 hands out the connection returned most recently, which keeps one connection hot when nothing else touches the pool. A pool built with `oldest_first` hands out the one returned longest ago instead, so a warmer that pings one connection at a time cycles through every connection in the pool rather than reusing the same one. Its empty places are reached in turn as well, so the warmer's first round opens every connection and a place freed by a failed request is filled again within one round.

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
        oldest_first=False,
        **keyword_arguments,
    ):
        """Builds the pool.

        Args:
            host (str): The host.
            port (int | None): The port.
            maximum_idle_seconds (float | None): How long a connection may sit idle and still be reused; None never refuses one.
            oldest_first (bool): Whether to hand out the connection returned longest ago rather than most recently.
            **keyword_arguments (object): The remaining urllib3 pool arguments.

        Returns:
            None: This method returns nothing.
        """
        if oldest_first:
            self.QueueCls = queue.Queue
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
        oldest_first=False,
        **keyword_arguments,
    ):
        """Builds the pool.

        Args:
            host (str): The host.
            port (int | None): The port.
            maximum_idle_seconds (float | None): How long a connection may sit idle and still be reused; None never refuses one.
            oldest_first (bool): Whether to hand out the connection returned longest ago rather than most recently.
            **keyword_arguments (object): The remaining urllib3 pool arguments.

        Returns:
            None: This method returns nothing.
        """
        if oldest_first:
            self.QueueCls = queue.Queue
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
        pool_size (int): How many connections the pool for each host keeps.
        oldest_first (bool): Whether the pools hand out the connection returned longest ago, which a warmed broker needs.
    """

    def __init__(
        self,
        maximum_idle_seconds,
        pool_size=DEFAULT_POOL_SIZE,
        oldest_first=False,
    ):
        """Builds the adapter with a chosen number of connections per host and no retries.

        Args:
            maximum_idle_seconds (float | None): How long a pooled connection may sit idle and still be reused.
            pool_size (int): How many connections the pool for each host keeps.
            oldest_first (bool): Whether the pools hand out the connection returned longest ago rather than most recently.

        Returns:
            None: This method returns nothing.
        """
        self.maximum_idle_seconds = maximum_idle_seconds
        self.pool_size = pool_size
        self.oldest_first = oldest_first
        super().__init__(pool_maxsize=pool_size)

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
                oldest_first=self.oldest_first,
            ),
            'https': functools.partial(
                IdleLimitedHTTPSConnectionPool,
                maximum_idle_seconds=self.maximum_idle_seconds,
                oldest_first=self.oldest_first,
            ),
        }
