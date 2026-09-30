"""Reads a Kotak session's stored login and logs in again only when the failed session id is still current.

`KotakSession` holds one `KotakAPI` and reads the stored login afresh on every connect. `current_login` returns the whole stored login, which the order socket needs for the host Kotak assigned the session, and `credentials` returns the access token and session id the quotes socket sends. `log_in_again` compares session ids: it logs in only when the session id a refused socket used is still the one in force.

Constructing the real `KotakAPI` logs in to Kotak, so the program registers a stand-in module under `stock_brokers.api.kotak`. Each construction counts as one login and issues the next numbered token and session id, and `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice the host in the stored login, and that the second request with the stale session id makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakSession/example_1_login_and_session_id.py
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
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    session_id = None
    login_count = 0


class StandInKotakAPI:
    """A stand-in for `KotakAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered access token and session id.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'kotak-token-{LoginRecord.login_count}'
        LoginRecord.session_id = f'kotak-sid-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, session id and host, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
            'sid': LoginRecord.session_id,
            'base_url': 'https://e21.kotaksecurities.com/',
        }


class LoginAndSessionIdExample:
    """Reads a Kotak session's login and asks it to log in again twice with the same session id.

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

    def run(self):
        """Prints the login and credentials around two login requests.

        Returns:
            None: This method returns nothing.
        """
        print(f'Stored login: {self.session.current_login()}')
        access_token, failed_session_id = self.session.credentials()
        print(f'Refused with {access_token} and {failed_session_id}')
        self.session.log_in_again(failed_session_id)
        self.session.log_in_again(failed_session_id)
        print(f'Credentials now: {self.session.credentials()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoginAndSessionIdExample().run()
