"""Catches a gateway error from Wisdom Capital through the base class that every broker's exception shares.

A load balancer in front of Wisdom Capital's API sometimes answers with an HTML page instead of JSON, for example a 502 Bad Gateway while the service behind it restarts. `WisdomCapitalAPI`'s `_request` cannot read an error code from such a page, so it raises `WisdomCapitalAPIException` with the HTTP status as `code` and the page's text as `message`.

Every broker's exception class derives from `BrokerAPIException`, so code that talks to several brokers can catch that one class and still read `code` and `message`. This program catches it that way.

The real constructor reads the broker's settings from MongoDB, probes `GET /interactive/user/balance` and the market data application's `clientConfig`, and logs in to Wisdom Capital with a session request for the interactive application and a second login for the market data application when the stored token no longer works. This program must never log in, so a small subclass, `WisdomCapitalAPIWithoutLogin`, skips that constructor and is handed the settings and a stand-in for Redis that already holds the stored login. `requests.request` is replaced, only while each request is sent, by a stand-in server that records the request and answers with a recorded-looking Wisdom Capital response, so nothing reaches the network.

Notice that the exception caught as `BrokerAPIException` is still a `WisdomCapitalAPIException`, and that its `code` is the integer 502 rather than a code of Wisdom Capital's own.

Run it from the project root:

    python examples/stock_brokers/api/wisdom_capital/WisdomCapitalAPIException/example_2_catching_a_gateway_error.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.base import (
    BrokerAPIException,
)
from stock_brokers.api.wisdom_capital import (
    WisdomCapitalAPI,
    WisdomCapitalAPIException,
)

STORED_LOGIN = {
    'broker_name': 'wisdom_capital',
    'access_token': 'morning-token',
    'last_login': '2026-09-30 07:00:05',
}

GATEWAY_PAGE = '<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center></body></html>'


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


class CatchingAGatewayErrorExample:
    """Sends a request that a gateway answers with an HTML error page and catches the result as a `BrokerAPIException`.

    Attributes:
        server (RecordedBrokerServer): The stand-in for Wisdom Capital's API, answering with a gateway error.
        api (WisdomCapitalAPIWithoutLogin): The API object being shown.
    """

    def __init__(self):
        """Stores a login and builds the API object and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        cache = SharedLoginCache()
        cache.hset('last_login', 'wisdom_capital', json.dumps(STORED_LOGIN))
        settings = {
            'ucc_code': 'WC0001',
        }
        self.server = RecordedBrokerServer(502, 'text/html; charset=utf-8', GATEWAY_PAGE)
        self.api = WisdomCapitalAPIWithoutLogin(cache, settings, STORED_LOGIN)

    def run(self):
        """Sends the request, catches the exception through the base class and prints what it holds.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch('requests.request', self.server.request):
            try:
                self.api.get(url='https://trade.wisdomcapital.in/interactive/user/balance?clientID=WC0001')
            except BrokerAPIException as error:
                print(f'Caught as BrokerAPIException: {type(error).__name__}')
                print(f'Is an instance of WisdomCapitalAPIException: {isinstance(error, WisdomCapitalAPIException)}')
                print(f'code: {error.code!r}')
                print(f'message: {error.message}')


if __name__ == '__main__':
    CatchingAGatewayErrorExample().run()
