"""Reads the UCC, session id and address a Kotak quotes socket needs for the SFeed market feed.

The SFeed market feed authenticates with the account's unique client code and the session id, not the access token. `KotakSession.feed_credentials` returns the `ucc_code` from Kotak's settings and the `sid` of the login in force now. `KotakSession.feed_url` returns the `feed_url` the login stored from Kotak's `feedUrl`, or Kotak's default address, `wss://sfeed.kotaksecurities.com/apifeed`, when the login stored none. Both read the stored login afresh on every call, so a login another process made is picked up at once.

Constructing the real `KotakAPI` logs in to Kotak, so the program registers a stand-in module under `stock_brokers.api.kotak`. Its `_settings` stands in for the MongoDB `settings` document, and `_current_login` answers from a shared record standing in for the Redis `last_login` hash. The program reads the feed's credentials and address once, then replaces the stored login as another process would, with a new session id and a feed address of its own, and reads them again.

Notice that the first address is Kotak's default because the first login stored none, and that the second reading shows the other process's session id and address without this session logging in.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakSession/example_3_market_feed_credentials_and_address.py
"""

import logging
import sys
import types

from stock_brokers.websockets.kotak import (
    KotakSession,
)


class LoginRecord:
    """The Kotak login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The access token in force now.
        session_id (str | None): The session id in force now.
        feed_url (str | None): The market feed address the login stored, None when it stored none.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    session_id = None
    feed_url = None
    login_count = 0


class StandInKotakAPI:
    """A stand-in for `KotakAPI` whose construction is a pretend login.

    Attributes:
        _settings (dict): The account's settings, as the real class reads them from MongoDB.
    """

    def __init__(self):
        """Logs in, which here only issues the next numbered access token and session id.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'ucc_code': 'ABCD1',
        }
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'kotak-token-{LoginRecord.login_count}'
        LoginRecord.session_id = f'kotak-sid-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, session id, host and feed address, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
            'sid': LoginRecord.session_id,
            'base_url': 'https://e21.kotaksecurities.com/',
            'feed_url': LoginRecord.feed_url,
        }


class MarketFeedCredentialsAndAddressExample:
    """Reads a Kotak session's market feed credentials and address before and after another process logs in.

    Attributes:
        session (KotakSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.kotak')
        api_module.KotakAPI = StandInKotakAPI
        sys.modules['stock_brokers.api.kotak'] = api_module
        self.session = KotakSession(logging.getLogger('kotak.session'))

    def print_feed_details(self):
        """Prints the market feed's credentials and address as the session reads them now.

        Returns:
            None: This method returns nothing.
        """
        ucc, session_id = self.session.feed_credentials()
        print(f'  feed_credentials: UCC {ucc}, session id {session_id}')
        print(f'  feed_url: {self.session.feed_url()}')

    def run(self):
        """Prints the feed details, replaces the stored login as another process would, and prints them again.

        Returns:
            None: This method returns nothing.
        """
        print("With this session's own login:")
        self.print_feed_details()
        LoginRecord.session_id = 'kotak-sid-from-another-process'
        LoginRecord.feed_url = 'wss://sfeed-e21.kotaksecurities.com/apifeed'
        print('After another process stored a new login:')
        self.print_feed_details()
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    MarketFeedCredentialsAndAddressExample().run()
