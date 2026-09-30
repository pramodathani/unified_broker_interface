"""Shows `IndMoneyInstruments.download` refusing to run when no token is stored and logging in fails.

When the ingester has no token from today, `download` calls `establish_session` to log IND Money in. If that login fails, `establish_session` prints why and returns None instead of raising, and `download` then raises a `ValueError` that says where to look, before sending any request, because IND Money would only answer an unauthenticated request with an error that says nothing about the cause.

Nothing here may reach MongoDB, Redis or IND Money, so for the length of the program the MongoDB and Redis clients of the session module and the instruments module are replaced by small stand-ins, and the session module's `api_class_for` is replaced so that constructing "the IND Money API class" calls `RefusedLogin.log_in`, which fails the way a rejected TOTP does. `requests.get` is replaced by a stand-in that counts requests, to show that none is sent.

Notice the line `establish_session` prints about the failed login, the `ValueError` that follows it, and that no download request was made.

Run it from the project root:

    python examples/stock_brokers/instruments/indmoney/IndMoneyInstruments/example_3_when_no_token_can_be_had.py
"""

import unittest.mock

import requests

from stock_brokers.api.indmoney import (
    INDMoneyAPIException,
)
from stock_brokers.api.utilities import session as session_module
from stock_brokers.instruments import indmoney as indmoney_instruments
from stock_brokers.instruments.indmoney import (
    IndMoneyInstruments,
)


class LoginStore:
    """A stand-in for MongoDB and its `last_login` collection, holding one login per broker.

    Attributes:
        logins (dict): Each broker name mapped to its stored login document.
    """

    def __init__(self, logins):
        """Holds the stored logins.

        Args:
            logins (dict): Each broker name mapped to its stored login document.

        Returns:
            None: This method returns nothing.
        """
        self.logins = logins

    def __getitem__(self, name):
        """Returns the store itself as the `last_login` collection, as `database['last_login']` does.

        Args:
            name (str): The collection name, always `last_login` here.

        Returns:
            LoginStore: This store.
        """
        return self

    def find_one(self, query, projection=None):
        """Finds the stored login of the broker the query names.

        Args:
            query (dict): The fields to match, here `broker_name`.
            projection (dict | None): The fields to return, which the stand-in ignores.

        Returns:
            dict | None: A copy of the stored login, or None when there is none.
        """
        login = self.logins.get(query['broker_name'])
        if login is None:
            return None
        return dict(login)


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


class RefusedLogin:
    """A stand-in for constructing `INDMoneyAPI`, whose login IND Money refuses."""

    def log_in(self):
        """Fails the login as IND Money does for a TOTP it rejects.

        Returns:
            None: This method never returns.

        Raises:
            INDMoneyAPIException: Always.
        """
        raise INDMoneyAPIException(code=401, message='Cannot generate access token from INDstocks API: invalid TOTP')


class CountingServer:
    """A stand-in for `requests.get` that only counts the requests it is sent.

    Attributes:
        requests_made (int): How many requests were sent.
    """

    def __init__(self):
        """Starts with no requests seen.

        Returns:
            None: This method returns nothing.
        """
        self.requests_made = 0

    def get(self, url, params=None, headers=None, timeout=None):
        """Counts one request and refuses it, in place of `requests.get`.

        Args:
            url (str): The instruments endpoint.
            params (dict | None): The query parameters.
            headers (dict | None): The request headers.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: Never returns.

        Raises:
            requests.ConnectionError: Always, since no request should be sent.
        """
        self.requests_made = self.requests_made + 1
        raise requests.ConnectionError('No request should have been sent.')


class WhenNoTokenCanBeHadExample:
    """Runs `download` with only yesterday's token stored and a login that fails.

    Attributes:
        store (LoginStore): The stand-in for MongoDB, holding yesterday's login.
        server (CountingServer): The stand-in for IND Money's endpoint.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.store = LoginStore({
            'indmoney': {
                'broker_name': 'indmoney',
                'access_token': 'indmoney-token-from-yesterday',
                'last_login': '2026-09-29 07:00:04',
            },
        })
        self.server = CountingServer()

    def run(self):
        """Builds the ingester, runs `download` and prints what it raised.

        Returns:
            None: This method returns nothing.
        """
        with (
            unittest.mock.patch.object(indmoney_instruments, 'get_mongo_db', return_value=self.store),
            unittest.mock.patch.object(session_module, 'get_mongo_db', return_value=self.store),
            unittest.mock.patch.object(session_module, 'get_cache', return_value=StandInRedis()),
            unittest.mock.patch.object(session_module, 'api_class_for', return_value=RefusedLogin().log_in),
            unittest.mock.patch.object(requests, 'get', self.server.get),
        ):
            instruments = IndMoneyInstruments()
            try:
                instruments.download()
            except ValueError as error:
                print(f'Raised ValueError: {error}')
        print(f'Download requests sent: {self.server.requests_made}')


if __name__ == '__main__':
    WhenNoTokenCanBeHadExample().run()
