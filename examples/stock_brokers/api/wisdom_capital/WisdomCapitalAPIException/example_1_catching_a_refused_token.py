"""Catches the `WisdomCapitalAPIException` that `WisdomCapitalAPI` raises when Wisdom Capital refuses the access token.

When Wisdom Capital answers with an HTTP error, `WisdomCapitalAPI`'s `_request` raises `WisdomCapitalAPIException` instead of returning an answer. Symphony XTS names the error in `code` and explains it in `description`, and `_request` copies both into the exception.

The real constructor reads the broker's settings from MongoDB, probes `GET /interactive/user/balance` and the market data application's `clientConfig`, and logs in to Wisdom Capital with a session request for the interactive application and a second login for the market data application when the stored token no longer works. This program must never log in, so a small subclass, `WisdomCapitalAPIWithoutLogin`, skips that constructor and is handed the settings and a stand-in for Redis that already holds the stored login. `requests.request` is replaced, only while each request is sent, by a stand-in server that records the request and answers with a recorded-looking Wisdom Capital response, so nothing reaches the network. Here the stand-in server answers with the HTTP 400 Wisdom Capital sends for a token it no longer accepts.

Notice that `code` holds Wisdom Capital's own error code rather than the HTTP status, so a caller can tell an expired token from other refusals.

Run it from the project root:

    python examples/stock_brokers/api/wisdom_capital/WisdomCapitalAPIException/example_1_catching_a_refused_token.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.wisdom_capital import (
    WisdomCapitalAPI,
    WisdomCapitalAPIException,
)

STORED_LOGIN = {
    'broker_name': 'wisdom_capital',
    'access_token': 'morning-token',
    'last_login': '2026-09-30 07:00:05',
}

REFUSAL = {
    'type': 'error',
    'code': 'e-token-0002',
    'description': 'Please Provide token to Authenticate',
}


class SharedLoginCache:
    """A dictionary-backed stand-in for Redis, holding the `last_login` hash that every process reads its token from.

    Attributes:
        hashes (dict): Each hash name mapped to a dictionary of its fields.
    """

    def __init__(self):
        """Starts with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}

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
        """Writes one field of a hash, as a login does.

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


class RecordedBrokerServer:
    """A stand-in for `requests.request` that answers every call with one recorded Wisdom Capital response and remembers what was sent.

    Attributes:
        status_code (int): The HTTP status every answer carries.
        content_type (str): The Content-Type header every answer carries.
        body (str): The body every answer carries.
        calls (list): One dictionary per request, holding its method, URL, headers, body and certificate setting.
    """

    def __init__(self, status_code, content_type, body):
        """Holds the answer to give.

        Args:
            status_code (int): The HTTP status every answer carries.
            content_type (str): The Content-Type header every answer carries.
            body (str): The body every answer carries.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.content_type = content_type
        self.body = body
        self.calls = []

    def request(self, method, url, **options):
        """Records one request and answers it, in place of `requests.request`.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            **options (Any): The remaining `requests.request` arguments, such as `headers` and `data`.

        Returns:
            requests.Response: The recorded answer.
        """
        self.calls.append({
            'method': method,
            'url': url,
            'headers': options.get('headers'),
            'data': options.get('data'),
            'verify': options.get('verify'),
        })
        response = requests.Response()
        response.status_code = self.status_code
        response.headers['Content-Type'] = self.content_type
        response._content = self.body.encode('utf-8')
        response.url = url
        return response


class WisdomCapitalAPIWithoutLogin(WisdomCapitalAPI):
    """A `WisdomCapitalAPI` that is handed its settings and cache instead of loading them and logging in.

    The real constructor reads the `wisdom_capital` settings document from MongoDB and then logs in to Wisdom Capital if the stored token no longer works. This subclass sets the same attributes from what it is given and does nothing else, so every request it makes still runs `WisdomCapitalAPI`'s own `_request`.
    """

    def __init__(self, cache, settings, stored_login):
        """Sets the attributes the real constructor would have loaded.

        MongoDB is left out because the stored login is handed in here and is already in the cache, which is the first place `_current_login` looks.

        Args:
            cache (SharedLoginCache): The stand-in for Redis, already holding the stored login.
            settings (dict): The broker's settings document.
            stored_login (dict): The broker's `last_login` document, as the real constructor reads it from MongoDB.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'wisdom_capital'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('wisdom_capital')
        self._settings = settings
        self._last_login = stored_login
        self.market_data_session_error = None


class CatchingARefusedTokenExample:
    """Sends a request that Wisdom Capital refuses and prints the exception it raises.

    Attributes:
        server (RecordedBrokerServer): The stand-in for Wisdom Capital's API, answering with a refusal.
        api (WisdomCapitalAPIWithoutLogin): The API object being shown.
    """

    def __init__(self):
        """Stores an expired login and builds the API object and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        cache = SharedLoginCache()
        cache.hset('last_login', 'wisdom_capital', json.dumps(STORED_LOGIN))
        settings = {
            'ucc_code': 'WC0001',
        }
        self.server = RecordedBrokerServer(400, 'application/json', json.dumps(REFUSAL))
        self.api = WisdomCapitalAPIWithoutLogin(cache, settings, STORED_LOGIN)

    def run(self):
        """Sends the request, catches the exception and prints its fields.

        Returns:
            None: This method returns nothing.
        """
        print(f'Wisdom Capital answers HTTP {self.server.status_code} with: {self.server.body}')
        with unittest.mock.patch('requests.request', self.server.request):
            try:
                self.api.get(url='https://trade.wisdomcapital.in/interactive/user/balance?clientID=WC0001')
            except WisdomCapitalAPIException as error:
                print(f'Caught: {type(error).__name__}')
                print(f'code: {error.code}')
                print(f'message: {error.message}')


if __name__ == '__main__':
    CatchingARefusedTokenExample().run()
