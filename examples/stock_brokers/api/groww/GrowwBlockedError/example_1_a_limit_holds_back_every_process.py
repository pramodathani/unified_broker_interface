"""Shows that one HTTP 429 from Groww stops every process from sending anything for a while.

Groww limits how many requests an account may send. Every request sent into that limit renews it, so a dozen Groww scripts retrying every few seconds keep the account limited all day. `GrowwAPI`'s `_request` therefore records a 429 in Redis, under `groww:api:blocked-until`, and every process reads that key before it sends anything.

The program builds two API objects, standing for two Groww scripts, over one stand-in for Redis. The first sends a request and Groww answers 429. The second then tries a request of its own. `GrowwAPIWithoutLogin` skips the real constructor, so nothing logs in, and `requests.request` is replaced by a stand-in server that counts what reaches it, so nothing reaches the network.

Notice that both objects raise `GrowwBlockedError`, but the server saw only the first request.

Run it from the project root:

    python examples/stock_brokers/api/groww/GrowwBlockedError/example_1_a_limit_holds_back_every_process.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.groww import (
    BLOCKED_KEY,
    GrowwAPI,
    GrowwBlockedError,
)

STORED_LOGIN = {
    'broker_name': 'groww',
    'access_token': 'morning-token',
    'last_login': '2026-10-18 06:00:00.335784',
}

RATE_LIMIT_ANSWER = {
    'status': 'FAILURE',
    'error': {
        'code': '429',
        'message': 'Rate limit has breached for your request. Please try again later.',
    },
}


class SharedCache:
    """A dictionary-backed stand-in for Redis, shared by every API object, as Redis is shared by every process.

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


class CountingBrokerServer:
    """A stand-in for `requests.request` that answers every call with HTTP 429 and counts the calls.

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
        """Counts one request and answers it with Groww's rate limit refusal.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            **options (Any): The remaining `requests.request` arguments.

        Returns:
            requests.Response: The refusal.
        """
        del method, options
        self.calls = self.calls + 1
        response = requests.Response()
        response.status_code = 429
        response.headers['Content-Type'] = 'application/json'
        response._content = json.dumps(RATE_LIMIT_ANSWER).encode('utf-8')
        response.url = url
        return response


class GrowwAPIWithoutLogin(GrowwAPI):
    """A `GrowwAPI` that is handed its cache and stored login instead of loading them and logging in."""

    def __init__(self, cache, name):
        """Sets the attributes the real constructor would have loaded.

        Args:
            cache (SharedCache): The stand-in for Redis.
            name (str): The script this object stands for, used as its logger's name.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'groww'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger(name)
        self._settings = {}
        self._last_login = STORED_LOGIN


class ALimitHoldsBackEveryProcessExample:
    """Sends a request that Groww limits, then a second request from another script.

    Attributes:
        cache (SharedCache): The stand-in for Redis that both scripts share.
        server (CountingBrokerServer): The stand-in for Groww's API.
    """

    def __init__(self):
        """Stores a login and builds the shared cache and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedCache()
        self.cache.hset('last_login', 'groww', json.dumps(STORED_LOGIN))
        self.server = CountingBrokerServer()

    def send(self, api, label):
        """Sends one request and prints the exception it raises.

        Args:
            api (GrowwAPIWithoutLogin): The API object to send through.
            label (str): Which script is sending, for the output.

        Returns:
            None: This method returns nothing.
        """
        try:
            api.get(url='https://api.groww.in/v1/margins/detail/user')
        except GrowwBlockedError as error:
            print(f'{label}: caught {type(error).__name__}, code {error.code}')

    def run(self):
        """Sends both requests and prints what reached the server.

        Returns:
            None: This method returns nothing.
        """
        funds_script = GrowwAPIWithoutLogin(self.cache, 'groww.funds')
        positions_script = GrowwAPIWithoutLogin(self.cache, 'groww.positions')
        with unittest.mock.patch('requests.request', self.server.request):
            self.send(funds_script, 'The funds script')
            print(f'A limit is recorded in Redis under {BLOCKED_KEY}: {self.cache.get(BLOCKED_KEY) is not None}')
            self.send(positions_script, 'The positions script')
        print(f'Requests that reached Groww: {self.server.calls}')


if __name__ == '__main__':
    ALimitHoldsBackEveryProcessExample().run()
