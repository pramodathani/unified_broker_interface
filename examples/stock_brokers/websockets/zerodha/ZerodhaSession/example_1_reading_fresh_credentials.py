"""Reads the Kite credentials a socket connects with, including a token another process has just obtained.

A `ZerodhaSession` builds one `ZerodhaAPI` and asks it for the current login every time a socket connects, so a token that another script or process obtained is picked up without restarting anything. This program shows that: it reads the credentials once, lets a pretend other process log in, and reads them again.

Constructing the real `ZerodhaAPI` logs in to Kite, so the program registers a stand-in module under `stock_brokers.api.zerodha` before building the session. The stand-in `ZerodhaAPI` counts its constructions as logins, keeps the api key in `_settings` the way the real class loads it from MongoDB, and answers `_current_login` from a shared record that stands in for the Redis `last_login` hash. No data store, network or broker is touched.

Notice that the second read returns the other process's token although the session itself logged in only once.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaSession/example_1_reading_fresh_credentials.py
"""

import logging
import sys
import types

from stock_brokers.websockets.zerodha import (
    ZerodhaSession,
)


class KiteLoginRecord:
    """The login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInZerodhaAPI:
    """A stand-in for `ZerodhaAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        KiteLoginRecord.login_count = KiteLoginRecord.login_count + 1
        KiteLoginRecord.access_token = f'kite-token-{KiteLoginRecord.login_count}'
        print(f'Stand-in login number {KiteLoginRecord.login_count}')
        self._settings = {
            'api_key': 'kite-api-key',
        }

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, or None before any login.
        """
        if KiteLoginRecord.access_token is None:
            return None
        return {
            'access_token': KiteLoginRecord.access_token,
        }


class ReadingFreshCredentialsExample:
    """Reads a session's credentials before and after another process logs in.

    Attributes:
        session (ZerodhaSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.zerodha')
        api_module.ZerodhaAPI = StandInZerodhaAPI
        sys.modules['stock_brokers.api.zerodha'] = api_module
        self.session = ZerodhaSession(logging.getLogger('zerodha.session'))

    def run(self):
        """Prints the credentials, pretends another process logged in, and prints them again.

        Returns:
            None: This method returns nothing.
        """
        api_key, access_token = self.session.credentials()
        print(f'Credentials now: api_key={api_key} access_token={access_token}')
        KiteLoginRecord.access_token = 'kite-token-from-another-process'
        print('Another process logged in.')
        api_key, access_token = self.session.credentials()
        print(f'Credentials now: api_key={api_key} access_token={access_token}')
        print(f'Logins made by this program: {KiteLoginRecord.login_count}')


if __name__ == '__main__':
    ReadingFreshCredentialsExample().run()
