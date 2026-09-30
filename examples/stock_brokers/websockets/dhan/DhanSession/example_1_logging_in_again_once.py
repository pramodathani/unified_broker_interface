"""Reads the Dhan credentials a socket connects with and logs in again only when the failed token is still current.

`DhanSession` holds one `DhanAPI` and asks it for the current login on every connect, so a token another process obtained is picked up at once. When a quotes socket is refused, it calls `log_in_again` with the token it used, and the session logs in only if that token is still the one in force, so several refused sockets cause one login between them.

Constructing the real `DhanAPI` logs in to Dhan, so the program registers a stand-in module under `stock_brokers.api.dhan` before building the session. Each construction of the stand-in counts as one login and issues the next numbered token; `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice that the first request logs in, that the second request with the same stale token is skipped, and that a token set by another process is what `credentials` returns next.

Run it from the project root:

    python examples/stock_brokers/websockets/dhan/DhanSession/example_1_logging_in_again_once.py
"""

import logging
import sys
import types

from stock_brokers.websockets.dhan import (
    DhanSession,
)


class LoginRecord:
    """The Dhan login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInDhanAPI:
    """A stand-in for `DhanAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'dhan-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'client_id': '1100012345',
        }

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
        }


class LoggingInAgainOnceExample:
    """Asks a Dhan session to log in again twice with the same failed token.

    Attributes:
        session (DhanSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.dhan')
        api_module.DhanAPI = StandInDhanAPI
        sys.modules['stock_brokers.api.dhan'] = api_module
        self.session = DhanSession(logging.getLogger('dhan.session'))

    def run(self):
        """Refuses the same token twice, then shows a token another process obtained.

        Returns:
            None: This method returns nothing.
        """
        client_id, failed_token = self.session.credentials()
        print(f'Client {client_id} was refused with {failed_token}')
        self.session.log_in_again(failed_token)
        print(f'Token in force: {self.session.credentials()[1]}')
        self.session.log_in_again(failed_token)
        print(f'Token in force after the second request: {self.session.credentials()[1]}')
        LoginRecord.access_token = 'dhan-token-from-another-process'
        print(f'Token in force after another process logged in: {self.session.credentials()[1]}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInAgainOnceExample().run()
