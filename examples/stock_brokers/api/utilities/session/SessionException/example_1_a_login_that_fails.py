"""Catches the `SessionException` that `ensure_session` raises when a broker's login fails.

`ensure_session` is how the candle downloaders and IND Money's instrument download make sure a broker is logged in. It takes a Redis lock so that only one process logs a broker in at a time, records the attempt so that a failing login is not retried more than once every five minutes, and then constructs the broker's API class, whose constructor does the login. Whatever goes wrong inside is re-raised as a `SessionException` naming the broker, with the original error kept as its cause, and the lock is released either way.

Constructing a real broker class would log in to that broker, so this program replaces three things in the session module for the length of the call: `get_cache` returns a small stand-in for Redis, `get_mongo_db` a stand-in for MongoDB with no stored login, and `api_class_for` a stand-in IND Money class whose constructor fails the way a rejected TOTP does. Nothing reaches a data store, the network or a broker.

Notice that the exception's cause is the broker's own error, that the lock is gone afterwards, and that the attempt was recorded but no success was.

Run it from the project root:

    python examples/stock_brokers/api/utilities/session/SessionException/example_1_a_login_that_fails.py
"""

import logging
import unittest.mock

from stock_brokers.api.indmoney import (
    INDMoneyAPIException,
)
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


class EmptyCollection:
    """A stand-in for a MongoDB collection that holds no documents."""

    def find_one(self, query, projection=None):
        """Finds nothing.

        Args:
            query (dict): The fields to match.
            projection (dict | None): The fields to return.

        Returns:
            None: There is never a match.
        """
        return None


class EmptyMongo:
    """A stand-in for the MongoDB database in which every collection is empty."""

    def __getitem__(self, name):
        """Returns an empty collection, as `database[name]` does.

        Args:
            name (str): The collection name.

        Returns:
            EmptyCollection: A collection with no documents.
        """
        return EmptyCollection()


class RefusedINDMoneyAPI:
    """A stand-in for `INDMoneyAPI` whose construction, the login, is refused."""

    def __init__(self):
        """Fails the login as IND Money does for a TOTP it rejects.

        Returns:
            None: This method never returns.

        Raises:
            INDMoneyAPIException: Always.
        """
        raise INDMoneyAPIException(code=401, message='Cannot generate access token from INDstocks API: invalid TOTP')


class ALoginThatFailsExample:
    """Asks for an IND Money session whose login fails and prints the resulting exception.

    Attributes:
        cache (StandInRedis): The stand-in for Redis, holding the lock and the attempt markers.
        logger (logging.Logger): Where `ensure_session` reports its progress.
    """

    def __init__(self):
        """Builds the stand-in Redis and the logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.logger = logging.getLogger('indmoney.session')

    def run(self):
        """Calls `ensure_session`, catches the `SessionException` and prints what it and Redis hold.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(session_module, 'get_cache', return_value=self.cache):
            with unittest.mock.patch.object(session_module, 'get_mongo_db', return_value=EmptyMongo()):
                with unittest.mock.patch.object(session_module, 'api_class_for', return_value=RefusedINDMoneyAPI):
                    try:
                        session_module.ensure_session('indmoney', logger=self.logger)
                    except SessionException as error:
                        print(f'Caught: {type(error).__name__}')
                        print(f'message: {error}')
                        print(f'cause: {type(error.__cause__).__name__} code={error.__cause__.code}')
        print(f'Login lock still held: {"ubi:login:indmoney" in self.cache.keys}')
        print(f'Attempt recorded: {"ubi:login-attempt:indmoney" in self.cache.keys}')
        print(f'Success recorded: {"ubi:login-ok:indmoney" in self.cache.keys}')


if __name__ == '__main__':
    ALoginThatFailsExample().run()
