"""Logs in to Kite again only when the token that failed is still the one in force.

Kite issues one token per session and every login invalidates the last, so when several sockets are refused at once only one of them should log in. `ZerodhaSession.log_in_again` takes the token the failing connection used and logs in only if that token is still current. This program asks it twice: first with the current token, which causes a login, and then with the same, now stale, token, which is skipped because the token has already been replaced.

Constructing the real `ZerodhaAPI` logs in to Kite, so the program registers a stand-in module under `stock_brokers.api.zerodha` before building the session. Each construction of the stand-in counts as one login and issues the next numbered token. No data store, network or broker is touched.

Notice that there are two logins in total, the one the session makes when it is built and the one the first request makes, and that the second request logs nothing.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaSession/example_2_logging_in_again_once.py
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


class LoggingInAgainOnceExample:
    """Asks a session to log in again twice with the same failed token.

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
        """Refuses the same token twice and prints the token in force after each request.

        Returns:
            None: This method returns nothing.
        """
        failed_token = self.session.credentials()[1]
        print(f'A socket was refused with {failed_token}')
        self.session.log_in_again(failed_token)
        print(f'Token in force: {self.session.credentials()[1]}')
        print(f'A second socket was refused with {failed_token}')
        self.session.log_in_again(failed_token)
        print(f'Token in force: {self.session.credentials()[1]}')
        print(f'Logins made: {KiteLoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInAgainOnceExample().run()
