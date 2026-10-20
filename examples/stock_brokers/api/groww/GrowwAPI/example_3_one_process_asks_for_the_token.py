"""Shows that when two Groww scripts find the session dead, only one of them asks Groww for a new token.

Groww's access token expires at 06:00 every day, and every Groww script builds its own `GrowwAPI`, so they all find the session dead at the same moment. If each asked Groww for a token, a dozen token requests would arrive at once, and on 2026-10-18 that, repeated every fifteen seconds as systemd restarted the failing scripts, used up the account's request limit.

`GrowwAPI`'s `_log_in` takes a Redis lock first. The script holding it asks Groww for the token and stores it; any script that then finds a login newer than the one it saw fail uses that login instead of asking again. A script that cannot take the lock waits for the token the holder stores.

The program runs two scripts' logins one after the other over one stand-in for Redis and one for MongoDB. `GrowwAPIWithoutLogin` skips the real constructor, and `requests.request` is replaced by a stand-in server that answers with a token and records what reaches it, so nothing reaches the network.

Notice that Groww received one token request, and that the second script ended up with the first script's token.

Run it from the project root:

    python examples/stock_brokers/api/groww/GrowwAPI/example_3_one_process_asks_for_the_token.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.groww import (
    TOKEN_LOCK_KEY,
    GrowwAPI,
)

EXPIRED_LOGIN = {
    'broker_name': 'groww',
    'access_token': 'yesterdays-token',
    'last_login': '2026-10-17 06:00:00.335784',
}

TOKEN_ANSWER = {
    'status': 'SUCCESS',
    'payload': {
        'token': 'todays-token',
    },
}


class SharedCache:
    """A dictionary-backed stand-in for Redis, shared by both scripts.

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


class LoginCollection:
    """A stand-in for MongoDB's `last_login` collection.

    Attributes:
        documents (dict): Each broker name mapped to its stored login.
    """

    def __init__(self):
        """Starts with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {}

    def replace_one(self, query, document, upsert=False):
        """Stores a login, as the real collection's `replace_one` does.

        Args:
            query (dict): Which document to replace, by `broker_name`.
            document (dict): The new document.
            upsert (bool): Whether to insert when none matches, which this stand-in always does.

        Returns:
            None: This method returns nothing.
        """
        del upsert
        self.documents[query['broker_name']] = document


class TokenServer:
    """A stand-in for `requests.request` that answers token requests with a new token and counts them.

    Attributes:
        token_requests (int): How many token requests reached the server.
    """

    def __init__(self):
        """Starts with no requests.

        Returns:
            None: This method returns nothing.
        """
        self.token_requests = 0

    def request(self, method, url, **options):
        """Counts one token request and answers it with a token.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            **options (Any): The remaining `requests.request` arguments.

        Returns:
            requests.Response: The token answer.
        """
        del method, options
        self.token_requests = self.token_requests + 1
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'application/json'
        response._content = json.dumps(TOKEN_ANSWER).encode('utf-8')
        response.url = url
        return response


class GrowwAPIWithoutLogin(GrowwAPI):
    """A `GrowwAPI` that is handed its stores and the login that just failed, instead of loading them."""

    def __init__(self, cache, logins, name):
        """Sets the attributes the real constructor would have loaded.

        Args:
            cache (SharedCache): The stand-in for Redis.
            logins (LoginCollection): The stand-in for MongoDB's `last_login` collection.
            name (str): The script this object stands for, used as its logger's name.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'groww'
        self._cache = cache
        self._mongo_db = {
            'last_login': logins,
        }
        self._logger = logging.getLogger(name)
        self._settings = {
            'totp_token': 'totp-api-token',
            'totp_secret': 'JBSWY3DPEHPK3PXP',
        }
        self._last_login = EXPIRED_LOGIN


class OneProcessAsksForTheTokenExample:
    """Logs two scripts in after the token expired and prints which token each ends up with.

    Attributes:
        cache (SharedCache): The stand-in for Redis.
        logins (LoginCollection): The stand-in for MongoDB's `last_login` collection.
        server (TokenServer): The stand-in for Groww's token endpoint.
    """

    def __init__(self):
        """Stores yesterday's login, which Groww no longer accepts.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedCache()
        self.cache.hset('last_login', 'groww', json.dumps(EXPIRED_LOGIN))
        self.logins = LoginCollection()
        self.server = TokenServer()

    def run(self):
        """Runs both logins and prints the outcome.

        Returns:
            None: This method returns nothing.
        """
        funds_script = GrowwAPIWithoutLogin(self.cache, self.logins, 'groww.funds')
        positions_script = GrowwAPIWithoutLogin(self.cache, self.logins, 'groww.positions')
        with unittest.mock.patch('requests.request', self.server.request):
            funds_script._log_in()
            positions_script._log_in()
        print(f'Token requests that reached Groww: {self.server.token_requests}')
        print(f"The funds script's token: {funds_script._last_login['access_token']}")
        print(f"The positions script's token: {positions_script._last_login['access_token']}")
        print(f"The token stored in MongoDB: {self.logins.documents['groww']['access_token']}")
        print(f'The token lock is still held: {self.cache.get(TOKEN_LOCK_KEY) is not None}')


if __name__ == '__main__':
    OneProcessAsksForTheTokenExample().run()
