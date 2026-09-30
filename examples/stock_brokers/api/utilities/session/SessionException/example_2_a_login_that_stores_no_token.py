"""Catches the `SessionException` that `ensure_session` raises when a login finishes without a usable token.

A broker class's constructor can return without an error and still leave no working token behind, for example when a broker changed its login answer and an earlier failed login had stored the string "None" in place of a token. `ensure_session` does not trust the constructor alone: after it returns, it reads the stored login from MongoDB again and raises a `SessionException` when the token there is missing or "None", so a caller never goes on to send requests with nothing to authenticate them.

Constructing a real broker class would log in to that broker, so this program replaces three things in the session module for the length of the call: `get_cache` returns a small stand-in for Redis, `get_mongo_db` a stand-in for MongoDB whose stored IND Money login holds "None", and `api_class_for` a stand-in IND Money class whose constructor returns quietly without storing anything. Nothing reaches a data store, the network or a broker.

Notice that this exception has no cause, because nothing inside raised, and that the lock was released before the stored login was checked.

Run it from the project root:

    python examples/stock_brokers/api/utilities/session/SessionException/example_2_a_login_that_stores_no_token.py
"""

import logging
import unittest.mock

from stock_brokers.api.utilities import session as session_module
from stock_brokers.api.utilities.session import (
    SessionException,
)


class StandInRedis:
    """A dictionary-backed stand-in for the Redis commands `ensure_session` uses.

    Attributes:
        keys (dict): Each key mapped to its value.
    """

    def __init__(self):
        """Starts with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.keys = {}

    def get(self, name):
        """Reads a key.

        Args:
            name (str): The key.

        Returns:
            str | None: The value, or None when the key is absent.
        """
        return self.keys.get(name)

    def set(self, name, value, nx=False, ex=None):
        """Sets a key, only when it is absent if `nx` is given.

        Args:
            name (str): The key.
            value (str): The value to store.
            nx (bool): True to set the key only when it does not exist.
            ex (int | None): The expiry in seconds, which the stand-in ignores.

        Returns:
            bool: True when the key was set.
        """
        if nx and name in self.keys:
            return False
        self.keys[name] = value
        return True

    def delete(self, name):
        """Removes a key.

        Args:
            name (str): The key.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if name in self.keys:
            del self.keys[name]
            return 1
        return 0


class StoredLoginCollection:
    """A stand-in for the MongoDB `last_login` collection, holding one document.

    Attributes:
        document (dict): The stored login.
    """

    def __init__(self, document):
        """Holds the stored login.

        Args:
            document (dict): The stored login.

        Returns:
            None: This method returns nothing.
        """
        self.document = document

    def find_one(self, query, projection=None):
        """Returns the stored login when the query names its broker.

        Args:
            query (dict): The fields to match, here `broker_name`.
            projection (dict | None): The fields to return, which the stand-in ignores.

        Returns:
            dict | None: A copy of the stored login, or None for another broker.
        """
        if query.get('broker_name') != self.document['broker_name']:
            return None
        return dict(self.document)


class StandInMongo:
    """A stand-in for the MongoDB database, holding only the `last_login` collection.

    Attributes:
        last_login (StoredLoginCollection): The `last_login` collection.
    """

    def __init__(self, last_login):
        """Holds the collection.

        Args:
            last_login (StoredLoginCollection): The `last_login` collection.

        Returns:
            None: This method returns nothing.
        """
        self.last_login = last_login

    def __getitem__(self, name):
        """Returns the `last_login` collection, as `database['last_login']` does.

        Args:
            name (str): The collection name, always `last_login` here.

        Returns:
            StoredLoginCollection: The collection.
        """
        return self.last_login


class QuietINDMoneyAPI:
    """A stand-in for `INDMoneyAPI` whose construction returns without storing a token."""

    def __init__(self):
        """Returns without doing anything, as a login that silently stored nothing would.

        Returns:
            None: This method returns nothing.
        """


class ALoginThatStoresNoTokenExample:
    """Asks for an IND Money session whose login leaves no usable token and prints the resulting exception.

    Attributes:
        cache (StandInRedis): The stand-in for Redis, holding the lock and the attempt markers.
        mongo_db (StandInMongo): The stand-in for MongoDB, holding a failed login.
        logger (logging.Logger): Where `ensure_session` reports its progress.
    """

    def __init__(self):
        """Builds the stand-in data stores and the logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.mongo_db = StandInMongo(StoredLoginCollection({
            'broker_name': 'indmoney',
            'access_token': 'None',
            'last_login': '2026-09-29 07:00:04',
        }))
        self.logger = logging.getLogger('indmoney.session')

    def run(self):
        """Calls `ensure_session`, catches the `SessionException` and prints what it and Redis hold.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(session_module, 'get_cache', return_value=self.cache):
            with unittest.mock.patch.object(session_module, 'get_mongo_db', return_value=self.mongo_db):
                with unittest.mock.patch.object(session_module, 'api_class_for', return_value=QuietINDMoneyAPI):
                    try:
                        session_module.ensure_session('indmoney', logger=self.logger)
                    except SessionException as error:
                        print(f'Caught: {type(error).__name__}')
                        print(f'message: {error}')
                        print(f'cause: {error.__cause__}')
        print(f'Login lock still held: {"ubi:login:indmoney" in self.cache.keys}')


if __name__ == '__main__':
    ALoginThatStoresNoTokenExample().run()
