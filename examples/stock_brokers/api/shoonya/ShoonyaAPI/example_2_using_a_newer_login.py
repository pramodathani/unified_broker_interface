"""Picks up an access token another process obtained, on the very next request.

Every Shoonya script builds its own `ShoonyaAPI`, and more than one of them may log in during a day. A login writes the new token to MongoDB and then to the Redis `last_login` hash, and `ShoonyaAPI`'s `_request` reads that hash again before every request, keeping whichever login is newer by its `last_login` time. So a token obtained by any process is used by every other one without restarting anything.

The program sends two requests through one API object. Between them it writes a newer login into the stand-in for Redis, as another process's login would.

The real constructor reads the broker's settings from MongoDB, probes `POST /NorenWClientAPI/UserDetails`, and logs in to Shoonya with a headless Chrome session and a TOTP when the stored token no longer works. This program must never log in, so a small subclass, `ShoonyaAPIWithoutLogin`, skips that constructor and is handed the settings and a stand-in for Redis that already holds the stored login. `requests.request` is replaced, only while each request is sent, by a stand-in server that records the request and answers with a recorded-looking Shoonya response, so nothing reaches the network.

Notice that the second request carries the newer token although the object was never rebuilt. The search text `M&M` also shows how the Noren form body is built: the ampersand is written as `\\u0026` inside `jData`, because Noren splits the body on a literal ampersand before it parses the JSON.

Run it from the project root:

    python examples/stock_brokers/api/shoonya/ShoonyaAPI/example_2_using_a_newer_login.py
"""

import json
import logging
import unittest.mock

import requests

from stock_brokers.api.shoonya import (
    ShoonyaAPI,
)

STORED_LOGIN = {
    'broker_name': 'shoonya',
    'access_token': 'morning-token',
    'last_login': '2026-09-30 07:00:05',
}

NEWER_LOGIN = {
    'broker_name': 'shoonya',
    'access_token': 'noon-token',
    'last_login': '2026-09-30 12:30:41',
}

RECORDED_ANSWER = {
    'stat': 'Ok',
    'values': [
        {
            'exch': 'NSE',
            'token': '2031',
            'tsym': 'M&M-EQ',
            'cname': 'MAHINDRA & MAHINDRA LTD',
            'instname': 'EQ',
            'pp': '2',
            'ls': '1',
            'ti': '0.10',
        },
    ],
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
    """A stand-in for `requests.request` that answers every call with one recorded Shoonya response and remembers what was sent.

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


class ShoonyaAPIWithoutLogin(ShoonyaAPI):
    """A `ShoonyaAPI` that is handed its settings and cache instead of loading them and logging in.

    The real constructor reads the `shoonya` settings document from MongoDB and then logs in to Shoonya if the stored token no longer works. This subclass sets the same attributes from what it is given and does nothing else, so every request it makes still runs `ShoonyaAPI`'s own `_request`.
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
        self._broker_name = 'shoonya'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('shoonya')
        self._settings = settings
        self._last_login = stored_login


class UsingANewerLoginExample:
    """Sends a request, lets another process log in, and sends another through the same object.

    Attributes:
        cache (SharedLoginCache): The stand-in for Redis, holding the shared login.
        server (RecordedBrokerServer): The stand-in for Shoonya's API.
        api (ShoonyaAPIWithoutLogin): The API object being shown.
        search_request (dict): The Noren search request, copied for each send because `_request` adds the user id to it.
    """

    def __init__(self):
        """Stores the morning login and builds the API object and the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        self.cache = SharedLoginCache()
        self.cache.hset('last_login', 'shoonya', json.dumps(STORED_LOGIN))
        settings = {
            'ucc_code': 'FA00001',
        }
        self.server = RecordedBrokerServer(200, 'application/json', json.dumps(RECORDED_ANSWER))
        self.api = ShoonyaAPIWithoutLogin(self.cache, settings, STORED_LOGIN)
        self.search_request = {
            'exch': 'NSE',
            'stext': 'M&M',
        }

    def credential(self, call):
        """The credential one recorded request carried.

        Args:
            call (dict): One request recorded by the stand-in server.

        Returns:
            str: The `jKey` field of the form body, which is where Noren expects the token.
        """
        body = call['data']
        return body.split('&jKey=')[1]

    def run(self):
        """Sends a request, writes a newer login, sends another request and prints what each carried.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch('requests.request', self.server.request):
            self.api.post(url='https://api.shoonya.com/NorenWClientAPI/SearchScrip', data=dict(self.search_request))
        print(f'First request carried: {self.credential(self.server.calls[0])}')
        self.cache.hset('last_login', 'shoonya', json.dumps(NEWER_LOGIN))
        print('Another process logged in again at 12:30:41 and wrote its login to Redis.')
        with unittest.mock.patch('requests.request', self.server.request):
            answer = self.api.post(url='https://api.shoonya.com/NorenWClientAPI/SearchScrip', data=dict(self.search_request))
        print(f'Second request carried: {self.credential(self.server.calls[1])}')
        print(f'Body sent: {self.server.calls[1]["data"]}')
        print(f'Request: {self.server.calls[1]["method"]} {self.server.calls[1]["url"]}')
        print(f'Status: {answer["status"]}, HTTP code: {answer["code"]}')
        print('Data:')
        print(json.dumps(answer['data'], indent=4))


if __name__ == '__main__':
    UsingANewerLoginExample().run()
