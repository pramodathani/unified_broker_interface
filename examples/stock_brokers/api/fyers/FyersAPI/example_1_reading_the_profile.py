"""Reads the account profile from Fyers's REST API with a stored access token.

`FyersAPI` is the object every Fyers script talks to the broker through. Its `get`, `post`, `put`, `patch` and `delete` methods all go through the broker's own `_request`, which adds the credentials of the login in force, sends the request, and wraps a successful answer in a dictionary with `status`, `code`, `data` and a `timestamp`.

The real constructor reads the broker's settings from MongoDB, probes `GET /api/v3/profile`, and logs in to Fyers with a five step exchange of an OTP, a TOTP and a PIN when the stored token no longer works. This program must never log in, so a small subclass, `FyersAPIWithoutLogin`, skips that constructor and is handed the settings and a stand-in for Redis that already holds the stored login. `requests.request` is replaced, only while each request is sent, by a stand-in server that records the request and answers with a recorded-looking Fyers response, so nothing reaches the network.

Notice the headers the request carried, which were built from the stored login and, where the broker needs them, from the settings, and that `data` holds only the `data` object, because `_request` unwraps the envelope Fyers puts around every answer. The `timestamp` is left out of the output because it is the moment the program ran.

Run it from the project root:

    python examples/stock_brokers/api/fyers/FyersAPI/example_1_reading_the_profile.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.fyers import (
    FyersAPI,
)

STORED_LOGIN = {
    'broker_name': 'fyers',
    'access_token': 'morning-token',
    'last_login': '2026-09-30 07:00:05',
}

RECORDED_ANSWER = {
    's': 'ok',
    'code': 200,
    'message': '',
    'data': {
        'fy_id': 'XD00001',
        'name': 'DEMO USER',
        'email_id': 'demo.user@example.com',
        'totp': True,
        'pwd_to_expire': 90,
        'ddpi_enabled': False,
        'mtf_enabled': False,
    },
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
    """A stand-in for `requests.request` that answers every call with one recorded Fyers response and remembers what was sent.

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


class FyersAPIWithoutLogin(FyersAPI):
    """A `FyersAPI` that is handed its settings and cache instead of loading them and logging in.

    The real constructor reads the `fyers` settings document from MongoDB and then logs in to Fyers if the stored token no longer works. This subclass sets the same attributes from what it is given and does nothing else, so every request it makes still runs `FyersAPI`'s own `_request`.
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
        self._broker_name = 'fyers'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('fyers')
        self._settings = settings
        self._last_login = stored_login


class ReadingTheProfileExample:
    """Sends one authenticated request through `FyersAPI` and prints what went out and what came back.

    Attributes:
        cache (SharedLoginCache): The stand-in for Redis, holding the stored login.
        server (RecordedBrokerServer): The stand-in for Fyers's API.
        api (FyersAPIWithoutLogin): The API object being shown.
    """

    def __init__(self):
        """Stores the morning login and builds the API object and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedLoginCache()
        self.cache.hset('last_login', 'fyers', json.dumps(STORED_LOGIN))
        settings = {
            'app_id': 'XB1234ABCD-100',
        }
        self.server = RecordedBrokerServer(200, 'application/json', json.dumps(RECORDED_ANSWER))
        self.api = FyersAPIWithoutLogin(self.cache, settings, STORED_LOGIN)

    def run(self):
        """Sends the request and prints the request and the answer.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch('requests.request', self.server.request):
            answer = self.api.get(url='https://api-t1.fyers.in/api/v3/profile')
        call = self.server.calls[0]
        print(f'Request: {call["method"]} {call["url"]}')
        print('Headers sent:')
        for name, value in call['headers'].items():
            print(f'    {name}: {value}')
        print(f'Status: {answer["status"]}')
        print(f'HTTP code: {answer["code"]}')
        print('Data:')
        print(json.dumps(answer['data'], indent=4))


if __name__ == '__main__':
    ReadingTheProfileExample().run()
