"""Shows which login `BrokerAPI` uses when MongoDB, Redis and the object itself disagree.

Before every request, a broker class calls `BrokerAPI._current_login` to choose the token to send. Redis's `last_login` hash is where every process publishes a new login, so it normally wins. When Redis holds nothing, the login is read from MongoDB and written into Redis only if the field is still empty, so it can fill the cache but never overwrite a login that lands in between. And when the object's own login is newer than Redis's by its `last_login` time, which happens when this object has just logged in but its write to Redis failed, the object keeps its own.

The program walks one object through those three cases with `get`. `ClockedBrokerAPI` is a made-up broker whose `_request` only reports the token it would send. Its constructor is the real `BrokerAPI.__init__`, run with `get_cache` and `get_mongo_db` replaced by small stand-ins for the length of the construction, so no data store is touched.

Notice that the second request picks up another process's newer token with no restart, and that the third keeps the object's own login because it is newer than the one in Redis.

Run it from the project root:

    python examples/stock_brokers/api/base/BrokerAPI/example_2_choosing_the_newer_login.py
"""

import json
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


class ClockedBrokerAPI(BrokerAPI):
    """A made-up broker whose requests only report the token they would carry."""

    def __init__(self):
        """Loads the settings and stored login through `BrokerAPI.__init__`, and skips the login a real broker would make.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(broker_name='clocked')

    def record_login_whose_redis_write_failed(self, access_token, moment):
        """Keeps a login this object has just made, as a real login does when its write to MongoDB succeeds and its write to Redis fails.

        Args:
            access_token (str): The new token.
            moment (str): When the login was made, as `%Y-%m-%d %H:%M:%S`.

        Returns:
            None: This method returns nothing.
        """
        self._last_login = {
            'broker_name': 'clocked',
            'access_token': access_token,
            'last_login': moment,
        }

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """Reports the login a request would carry, without sending anything.

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
            json (dict | None): A JSON body, unused here.
            verbose (bool): Whether to log the request, unused here.

        Returns:
            dict: `status`, `code` and `data`, where `data` is the login the request would carry.
        """
        login = self._current_login()
        return {
            'status': 'success',
            'code': 200,
            'data': login,
        }


class ChoosingTheNewerLoginExample:
    """Sends three requests through one object while the stored logins change around it.

    Attributes:
        cache (StandInRedis): The stand-in for Redis, empty at first.
        mongo_db (StandInMongo): The stand-in for MongoDB, holding the settings and the morning login.
        url (str): The URL every request names.
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
                    'broker_name': 'clocked',
                    'client_id': 'CLOCK01',
                },
            ]),
            'last_login': StandInCollection([
                {
                    'broker_name': 'clocked',
                    'access_token': 'morning-token',
                    'last_login': '2026-09-30 07:00:05',
                },
            ]),
        })
        self.url = 'https://clocked.example/user/profile'

    def show(self, case, answer):
        """Prints which login a request carried and what Redis holds afterwards.

        Args:
            case (str): What the request shows.
            answer (dict): What the request returned.

        Returns:
            None: This method returns nothing.
        """
        login = answer['data']
        print(case)
        print(f'    sent {login["access_token"]} (logged in at {login["last_login"]})')
        print(f'    Redis last_login now: {self.cache.hget("last_login", "clocked")}')

    def run(self):
        """Builds the object and sends the three requests.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(broker_api_base, 'get_cache', return_value=self.cache):
            with unittest.mock.patch.object(broker_api_base, 'get_mongo_db', return_value=self.mongo_db):
                api = ClockedBrokerAPI()
        self.show('1. Redis is empty, so the login is read from MongoDB and cached:', api.get(url=self.url))
        newer_login = {
            'broker_name': 'clocked',
            'access_token': 'noon-token',
            'last_login': '2026-09-30 12:30:41',
        }
        self.cache.hset('last_login', 'clocked', json.dumps(newer_login))
        self.show('2. Another process logged in at 12:30:41 and wrote Redis:', api.get(url=self.url))
        api.record_login_whose_redis_write_failed('evening-token', '2026-09-30 18:02:10')
        self.show('3. This object logged in at 18:02:10 but could not write Redis:', api.get(url=self.url))


if __name__ == '__main__':
    ChoosingTheNewerLoginExample().run()
