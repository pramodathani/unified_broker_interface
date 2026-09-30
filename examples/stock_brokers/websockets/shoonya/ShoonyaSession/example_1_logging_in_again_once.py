"""Builds a Shoonya session, reads its credentials and logs in again only when the failed token is still current.

Shoonya's login drives a headless Chrome session, so `ShoonyaSession` makes sure refused sockets log in one at a time: `log_in_again` logs in only when the token a refused socket used is still the one in force, so several refused sockets cause one login between them. `credentials` returns the account's UCC code, which Noren takes as the user id, and the token in force now.

Constructing the real `ShoonyaAPI` logs in to Shoonya, so the program registers a stand-in module under `stock_brokers.api.shoonya`. Each construction of the stand-in counts as a login and issues the next numbered token, `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice that the second request with the same stale token makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/shoonya/ShoonyaSession/example_1_logging_in_again_once.py
"""

import logging
import sys
import types

from stock_brokers.websockets.shoonya import (
    ShoonyaSession,
)


class LoginRecord:
    """The Shoonya login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInShoonyaAPI:
    """A stand-in for `ShoonyaAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'shoonya-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'ucc_code': 'FA12345',
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
    """Builds a Shoonya session and asks it to log in again twice with the same token.

    Attributes:
        session (ShoonyaSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.shoonya')
        api_module.ShoonyaAPI = StandInShoonyaAPI
        sys.modules['stock_brokers.api.shoonya'] = api_module
        self.session = ShoonyaSession(logging.getLogger('shoonya.session'))

    def run(self):
        """Refuses the same token twice and prints the credentials after each request.

        Returns:
            None: This method returns nothing.
        """
        user_id, failed_token = self.session.credentials()
        print(f'User {user_id} was refused with {failed_token}')
        self.session.log_in_again(failed_token)
        print(f'Credentials now: {self.session.credentials()}')
        self.session.log_in_again(failed_token)
        print(f'Credentials after the second request: {self.session.credentials()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInAgainOnceExample().run()
