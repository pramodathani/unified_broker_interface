"""Writes a small broker class on `BrokerAPI` and sends one request with each HTTP verb through it.

A broker module subclasses `BrokerAPI` and supplies two things: a constructor that calls `BrokerAPI.__init__` and then logs in when the stored token no longer works, and a `_request` that sends one request with the broker's credentials. `BrokerAPI` supplies the rest: `get`, `post`, `put`, `patch` and `delete` each pass their arguments to `_request` with the matching method, and `__init__` loads the broker's settings and stored login.

The broker here, `PaperBrokerAPI`, is made up. Its `_request` answers from memory instead of the network, keeping a small list of watchlists, and it reads the token in force through `_current_login` as the real brokers do. Its constructor skips the login, because there is nothing to log in to.

`BrokerAPI.__init__` itself reads the settings and the stored login from MongoDB and copies the settings into the Redis `settings` hash. The program runs that real constructor, with `get_cache` and `get_mongo_db` replaced for the length of the construction by small stand-ins, so no data store is touched.

Notice that the constructor copied the settings into Redis but not the login: only a login writes the Redis `last_login` hash, so that a constructor can never put an older token back over a newer one.

Run it from the project root:

    python examples/stock_brokers/api/base/BrokerAPI/example_1_writing_a_broker_class.py
"""

import unittest.mock

from stock_brokers.api import base as broker_api_base
from stock_brokers.api.base import (
    BrokerAPI,
)


class StandInCollection:
    """A stand-in for one MongoDB collection, holding documents in a list.

    Attributes:
        documents (list): The stored documents.
    """

    def __init__(self, documents):
        """Holds the documents.

        Args:
            documents (list): The documents the collection starts with.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def find_one(self, query, projection=None):
        """Finds the first document whose fields match every field of the query.

        Args:
            query (dict): The fields to match.
            projection (dict | None): Fields to leave out, which the stand-in honours only for `_id`.

        Returns:
            dict | None: A copy of the document, or None when nothing matches.
        """
        for document in self.documents:
            matches = True
            for field, value in query.items():
                if document.get(field) != value:
                    matches = False
            if matches:
                found = dict(document)
                found.pop('_id', None)
                return found
        return None


class StandInMongo:
    """A stand-in for the MongoDB database, holding the `settings` and `last_login` collections.

    Attributes:
        collections (dict): Each collection name mapped to its `StandInCollection`.
    """

    def __init__(self, collections):
        """Holds the collections.

        Args:
            collections (dict): Each collection name mapped to its `StandInCollection`.

        Returns:
            None: This method returns nothing.
        """
        self.collections = collections

    def __getitem__(self, name):
        """Returns one collection, as `database[name]` does.

        Args:
            name (str): The collection name.

        Returns:
            StandInCollection: The collection.
        """
        return self.collections[name]


class StandInRedis:
    """A dictionary-backed stand-in for the Redis client's hash commands.

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

    def hsetnx(self, name, key, value):
        """Writes one field of a hash only when it is empty.

        Args:
            name (str): The hash name.
            key (str): The field name.
            value (str): The value to store.

        Returns:
            int: 1 when the field was written, 0 when it already held a value.
        """
        if self.hget(name, key) is not None:
            return 0
        return self.hset(name, key, value)


class PaperBrokerAPI(BrokerAPI):
    """A made-up broker that keeps watchlists in memory, written the way a real broker module is.

    Attributes:
        watchlists (dict): Each watchlist id mapped to its name and symbols.
    """

    def __init__(self):
        """Loads the settings and stored login through `BrokerAPI.__init__`, and skips the login a real broker would make.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(broker_name='paper')
        self.watchlists = {}

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """Answers one request from memory, in the shape every broker's `_request` returns.

        Args:
            method (str): The HTTP method.
            url (str): The URL requested.
            params (dict | None): Query parameters, unused here.
            data (Any): A form body, unused here.
            headers (dict | None): Headers, unused here.
            cookies (dict | None): Cookies, unused here.
            files (dict | None): Files, unused here.
            auth (Any): Authentication, unused here.
            timeout (float | None): A timeout, unused here.
            allow_redirects (bool | None): Whether to follow redirects, unused here.
            proxies (dict | None): Proxies, unused here.
            hooks (dict | None): Request hooks, unused here.
            stream (bool | None): Whether to stream, unused here.
            verify (bool | None): Whether to check certificates, unused here.
            cert (Any): A client certificate, unused here.
            json (dict | None): A JSON body, holding the watchlist's fields.
            verbose (bool): Whether to log the request, unused here.

        Returns:
            dict: `status`, `code` and `data`, where `data` holds the watchlists and the token the request would have carried.
        """
        login = self._current_login()
        watchlist_id = url.rsplit('/', 1)[-1]
        if method == 'POST' or method == 'PUT':
            self.watchlists[watchlist_id] = dict(json)
        elif method == 'PATCH':
            self.watchlists[watchlist_id].update(json)
        elif method == 'DELETE':
            del self.watchlists[watchlist_id]
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'token': login['access_token'],
                'watchlists': dict(self.watchlists),
            },
        }


class WritingABrokerClassExample:
    """Builds `PaperBrokerAPI` through the real `BrokerAPI` constructor and calls every verb once.

    Attributes:
        cache (StandInRedis): The stand-in for Redis.
        mongo_db (StandInMongo): The stand-in for MongoDB, holding the settings and the stored login.
    """

    def __init__(self):
        """Builds the stand-in data stores.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.mongo_db = StandInMongo({
            'settings': StandInCollection([
                {
                    '_id': 'settings-1',
                    'broker_name': 'paper',
                    'client_id': 'PAPER01',
                },
            ]),
            'last_login': StandInCollection([
                {
                    '_id': 'login-1',
                    'broker_name': 'paper',
                    'access_token': 'paper-token',
                    'last_login': '2026-09-30 07:00:05',
                },
            ]),
        })

    def show(self, verb, answer):
        """Prints one answer on one line.

        Args:
            verb (str): The method that was called.
            answer (dict): What it returned.

        Returns:
            None: This method returns nothing.
        """
        print(f'{verb}: status={answer["status"]} token={answer["data"]["token"]} watchlists={answer["data"]["watchlists"]}')

    def run(self):
        """Builds the broker object, sends one request per verb and prints each answer.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(broker_api_base, 'get_cache', return_value=self.cache):
            with unittest.mock.patch.object(broker_api_base, 'get_mongo_db', return_value=self.mongo_db):
                api = PaperBrokerAPI()
        print(f'Redis settings hash after construction: {self.cache.hashes.get("settings")}')
        print(f'Redis last_login hash after construction: {self.cache.hashes.get("last_login")}')
        url = 'https://paper.example/watchlists/banks'
        new_watchlist = {
            'name': 'Banks',
            'symbols': [
                'NSE:HDFCBANK',
            ],
        }
        replacement = {
            'name': 'Banks',
            'symbols': [
                'NSE:HDFCBANK',
                'NSE:ICICIBANK',
            ],
        }
        rename = {
            'name': 'Private banks',
        }
        self.show('post', api.post(url=url, json=new_watchlist))
        self.show('get', api.get(url=url))
        self.show('put', api.put(url=url, json=replacement))
        self.show('patch', api.patch(url=url, json=rename))
        self.show('delete', api.delete(url=url))

if __name__ == '__main__':
    WritingABrokerClassExample().run()
