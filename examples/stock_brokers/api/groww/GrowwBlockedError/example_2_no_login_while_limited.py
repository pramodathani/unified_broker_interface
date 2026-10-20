"""Shows that no login is sent while Groww is limiting the account, and that the login lock is let go.

At 06:00 every day Groww's access token expires, and every Groww script finds the session dead at once. A login sent while Groww is limiting the account only renews the limit, so `GrowwAPI`'s `_log_in` stops before asking Groww for a token whenever a 429 is recorded in Redis. It still releases the token lock it took, so the next attempt, once the limit has lifted, is not held up.

The program records a limit as another script's 429 would, then asks an API object to log in. `GrowwAPIWithoutLogin` skips the real constructor, and `requests.request` is replaced by a stand-in that counts what reaches it, so nothing reaches the network.

Notice that the login raises `GrowwBlockedError`, Groww saw no request, and the lock key is gone afterwards.

Run it from the project root:

    python examples/stock_brokers/api/groww/GrowwBlockedError/example_2_no_login_while_limited.py
"""

import json
import logging
import time
import unittest.mock

from stock_brokers.api.groww import (
    BLOCKED_KEY,
    TOKEN_LOCK_KEY,
    GrowwAPI,
    GrowwBlockedError,
)

STORED_LOGIN = {
    'broker_name': 'groww',
    'access_token': 'yesterdays-token',
    'last_login': '2026-10-17 06:00:00.335784',
}


class SharedCache:
    """A dictionary-backed stand-in for Redis, holding plain keys and hashes.

    Attributes:
        hashes (dict): Each hash name mapped to a dictionary of its fields.
        values (dict): Each plain key mapped to its value.
    """

    def __init__(self):
        """Starts with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.values = {}

    def hget(self, name, key):
        """Reads one field of a hash.

        Args:
            name (str): The hash name.
            key (str): The field name.

        Returns:
            str | None: The stored value, or None when there is none.
        """
        fields = self.hashes.get(name, {})
        return fields.get(key)

    def hset(self, name, key, value):
        """Writes one field of a hash.

        Args:
            name (str): The hash name.
            key (str): The field name.
            value (str): The value to store.

        Returns:
            int: Always 1, the number of fields Redis reports written.
        """
        if name not in self.hashes:
            self.hashes[name] = {}
        self.hashes[name][key] = value
        return 1

    def get(self, name):
        """Reads a plain key.

        Args:
            name (str): The key.

        Returns:
            str | None: The stored value, or None when there is none.
        """
        return self.values.get(name)

    def set(self, name, value, nx=False, ex=None):
        """Writes a plain key; the expiry is accepted and ignored.

        Args:
            name (str): The key.
            value (str): The value.
            nx (bool): Write only when the key does not exist.
            ex (int | None): The expiry in seconds, which this stand-in does not apply.

        Returns:
            bool: Whether the value was written.
        """
        del ex
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    def delete(self, name):
        """Removes a plain key.

        Args:
            name (str): The key.

        Returns:
            int: How many keys were removed.
        """
        if name in self.values:
            del self.values[name]
            return 1
        return 0


class CountingBrokerServer:
    """A stand-in for `requests.request` that only counts calls; none should arrive.

    Attributes:
        calls (int): How many requests reached the server.
    """

    def __init__(self):
        """Starts with no calls.

        Returns:
            None: This method returns nothing.
        """
        self.calls = 0

    def request(self, method, url, **options):
        """Counts a request that should never have been sent.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            **options (Any): The remaining `requests.request` arguments.

        Returns:
            None: Nothing, because no answer is expected.

        Raises:
            RuntimeError: Always, because a request reached the network.
        """
        del method, url, options
        self.calls = self.calls + 1
        raise RuntimeError('A request was sent while Groww was limiting the account.')


class GrowwAPIWithoutLogin(GrowwAPI):
    """A `GrowwAPI` that is handed its cache, settings and stored login instead of loading them."""

    def __init__(self, cache):
        """Sets the attributes the real constructor would have loaded.

        Args:
            cache (SharedCache): The stand-in for Redis.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'groww'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('groww.funds')
        self._settings = {
            'totp_token': 'totp-api-token',
            'totp_secret': 'JBSWY3DPEHPK3PXP',
        }
        self._last_login = STORED_LOGIN


class NoLoginWhileLimitedExample:
    """Records a limit, asks for a login, and prints what happened.

    Attributes:
        cache (SharedCache): The stand-in for Redis.
        server (CountingBrokerServer): The stand-in for Groww's API.
    """

    def __init__(self):
        """Stores yesterday's login and a limit another script recorded.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedCache()
        self.cache.hset('last_login', 'groww', json.dumps(STORED_LOGIN))
        self.cache.set(BLOCKED_KEY, str(time.time() + 300))
        self.server = CountingBrokerServer()

    def run(self):
        """Asks for a login and prints the outcome.

        Returns:
            None: This method returns nothing.
        """
        api = GrowwAPIWithoutLogin(self.cache)
        with unittest.mock.patch('requests.request', self.server.request):
            try:
                api._log_in()
            except GrowwBlockedError as error:
                print(f'The login raised {type(error).__name__}, code {error.code}')
        print(f'Requests that reached Groww: {self.server.calls}')
        print(f'The token lock is still held: {self.cache.get(TOKEN_LOCK_KEY) is not None}')


if __name__ == '__main__':
    NoLoginWhileLimitedExample().run()
