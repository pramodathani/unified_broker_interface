"""Catches the `GrowwAPIException` raised for an error answer that is not in Groww's usual shape.

Groww usually nests an error under `error` with a `code` and a `message`, and `_request` copies those into the exception. Some answers carry an `error` without both of them. `_request` used to raise only for the usual shape, so such an answer made it return nothing at all, and the caller then failed with a `TypeError` that hid what Groww had said. On 2026-10-18 that is how the Groww funds script reported its failed 06:00 login.

Now every error status raises. When the usual fields are missing, the HTTP status is the `code` and the whole body is the `message`, and `status_code` always holds the HTTP status.

`GrowwAPIWithoutLogin` skips the real constructor, so nothing logs in, and `requests.request` is replaced by a stand-in server that answers HTTP 400 with an `error` that is a plain string, so nothing reaches the network.

Run it from the project root:

    python examples/stock_brokers/api/groww/GrowwAPIException/example_3_an_error_without_a_message.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.groww import (
    GrowwAPI,
    GrowwAPIException,
)

STORED_LOGIN = {
    'broker_name': 'groww',
    'access_token': 'morning-token',
    'last_login': '2026-10-18 06:00:00.335784',
}

UNUSUAL_ANSWER = {
    'status': 'FAILURE',
    'error': 'TOTP already used',
}


class SharedLoginCache:
    """A dictionary-backed stand-in for Redis, holding the `last_login` hash.

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


class RecordedBrokerServer:
    """A stand-in for `requests.request` that answers every call with one recorded response.

    Attributes:
        status_code (int): The HTTP status every answer carries.
        body (str): The body every answer carries.
    """

    def __init__(self, status_code, body):
        """Holds the answer to give.

        Args:
            status_code (int): The HTTP status every answer carries.
            body (str): The body every answer carries.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body

    def request(self, method, url, **options):
        """Answers one request with the recorded response.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            **options (Any): The remaining `requests.request` arguments.

        Returns:
            requests.Response: The recorded answer.
        """
        del method, options
        response = requests.Response()
        response.status_code = self.status_code
        response.headers['Content-Type'] = 'application/json'
        response._content = self.body.encode('utf-8')
        response.url = url
        return response


class GrowwAPIWithoutLogin(GrowwAPI):
    """A `GrowwAPI` that is handed its cache and stored login instead of loading them and logging in."""

    def __init__(self, cache):
        """Sets the attributes the real constructor would have loaded.

        Args:
            cache (SharedLoginCache): The stand-in for Redis, already holding the stored login.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'groww'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('groww')
        self._settings = {}
        self._last_login = STORED_LOGIN


class AnErrorWithoutAMessageExample:
    """Sends a request that Groww refuses in an unusual shape and prints the exception.

    Attributes:
        server (RecordedBrokerServer): The stand-in for Groww's API.
        api (GrowwAPIWithoutLogin): The API object being shown.
    """

    def __init__(self):
        """Stores a login and builds the API object and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        cache = SharedLoginCache()
        cache.hset('last_login', 'groww', json.dumps(STORED_LOGIN))
        self.server = RecordedBrokerServer(400, json.dumps(UNUSUAL_ANSWER))
        self.api = GrowwAPIWithoutLogin(cache)

    def run(self):
        """Sends the request, catches the exception and prints its fields.

        Returns:
            None: This method returns nothing.
        """
        print(f'Groww answers HTTP {self.server.status_code} with: {self.server.body}')
        with unittest.mock.patch('requests.request', self.server.request):
            try:
                self.api.post(url='https://api.groww.in/v1/token/api/access', data='{}')
            except GrowwAPIException as error:
                print(f'Caught: {type(error).__name__}')
                print(f'code: {error.code}')
                print(f'status_code: {error.status_code}')
                print(f'message: {error.message}')


if __name__ == '__main__':
    AnErrorWithoutAMessageExample().run()
