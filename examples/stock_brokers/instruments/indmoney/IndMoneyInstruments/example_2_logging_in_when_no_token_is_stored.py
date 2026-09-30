"""Logs IND Money in with `establish_session` when the only stored token is from an earlier day, then downloads with the new one.

IND Money's tokens last twenty-four hours, so when the ingester is built without a token it reads the stored login from MongoDB and keeps the token only if it was issued today. The daily download runs before the morning login refresh, so on most weekdays the stored token is yesterday's and nothing is kept. `establish_session` then logs IND Money in through `ensure_session`, which shares a Redis lock and a retry limit with every other process logging brokers in, and returns the token the login stored. `download` does this itself whenever it has no token; the program calls it directly to show its result.

Nothing here may reach MongoDB, Redis or IND Money, so for the length of the program the MongoDB and Redis clients of the session module and the instruments module are replaced by small stand-ins, the session module's `api_class_for` is replaced so that constructing "the IND Money API class" calls `StandInLogin.log_in`, which stores a new login dated today, and `requests.get` is replaced by a stand-in that answers each source with a canned CSV file.

Notice that the ingester starts with no token although one is stored, that one login produces the token, and that all three downloads carry it.

Run it from the project root:

    python examples/stock_brokers/instruments/indmoney/IndMoneyInstruments/example_2_logging_in_when_no_token_is_stored.py
"""

import datetime
import unittest.mock

import requests

from stock_brokers.api.utilities import session as session_module
from stock_brokers.instruments import indmoney as indmoney_instruments
from stock_brokers.instruments.indmoney import (
    IndMoneyInstruments,
)

CSV_FILE = (
    'exch,segment,security_id,instrument_name,trading_symbol,lot_units,tick_size,series,symbol_name,isin\n'
    'NSE,E,1594,EQUITY,INFY,1,0.1,EQ,INFOSYS LIMITED,INE009A01021\n'
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


class StandInLogin:
    """A stand-in for constructing `INDMoneyAPI`, whose construction is the login.

    Attributes:
        store (LoginStore): Where the login is stored, as the real login writes MongoDB.
        logins_made (int): How many logins have been made.
    """

    def __init__(self, store):
        """Holds the store the login writes to.

        Args:
            store (LoginStore): Where the login is stored.

        Returns:
            None: This method returns nothing.
        """
        self.store = store
        self.logins_made = 0

    def log_in(self):
        """Stores a new IND Money login dated now, as a successful real login does.

        Returns:
            None: This method returns nothing.
        """
        self.logins_made = self.logins_made + 1
        self.store.logins['indmoney'] = {
            'broker_name': 'indmoney',
            'access_token': 'indmoney-token-from-login',
            'last_login': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }


class CsvServer:
    """A stand-in for `requests.get` that answers every source with the same canned CSV file.

    Attributes:
        authorizations (list): The `Authorization` header of every request, in order.
    """

    def __init__(self):
        """Starts with no requests seen.

        Returns:
            None: This method returns nothing.
        """
        self.authorizations = []

    def get(self, url, params=None, headers=None, timeout=None):
        """Answers one source's request, in place of `requests.get`.

        Args:
            url (str): The instruments endpoint.
            params (dict | None): The query parameters, naming the source.
            headers (dict | None): The request headers, carrying the token.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: A successful answer carrying the canned file.
        """
        self.authorizations.append(headers['Authorization'])
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.encoding = 'utf-8'
        response._content = CSV_FILE.encode('utf-8')
        response.url = url
        return response


class LoggingInWhenNoTokenIsStoredExample:
    """Builds the ingester with only yesterday's token stored, logs in, and downloads.

    Attributes:
        store (LoginStore): The stand-in for MongoDB, holding yesterday's login.
        login (StandInLogin): The stand-in for the IND Money login.
        server (CsvServer): The stand-in for IND Money's endpoint.
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
        self.login = StandInLogin(self.store)
        self.server = CsvServer()

    def run(self):
        """Builds the ingester, establishes a session, downloads, and prints each step's result.

        Returns:
            None: This method returns nothing.
        """
        with (
            unittest.mock.patch.object(indmoney_instruments, 'get_mongo_db', return_value=self.store),
            unittest.mock.patch.object(session_module, 'get_mongo_db', return_value=self.store),
            unittest.mock.patch.object(session_module, 'get_cache', return_value=StandInRedis()),
            unittest.mock.patch.object(session_module, 'api_class_for', return_value=self.login.log_in),
            unittest.mock.patch.object(requests, 'get', self.server.get),
        ):
            instruments = IndMoneyInstruments()
            print(f'Token kept at construction: {instruments.access_token}')
            instruments.access_token = instruments.establish_session()
            print(f'Token after establish_session: {instruments.access_token}')
            print(f'Logins made: {self.login.logins_made}')
            frame = instruments.download()
        print(f'Download requests carried: {self.server.authorizations}')
        print(f'Rows: {len(frame)}')


if __name__ == '__main__':
    LoggingInWhenNoTokenIsStoredExample().run()
