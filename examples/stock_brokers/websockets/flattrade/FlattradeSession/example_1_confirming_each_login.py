"""Builds a Flattrade session, reads its credentials and logs in again only when the failed token is still current.

Noren refuses a dead session inside an HTTP 200 answer, so a `FlattradeAPI` that constructed without error is no proof of a working session. `FlattradeSession` therefore confirms every login by calling UserDetails, and `log_in_again` logs in only when the token a refused socket used is still the one in force, so several refused sockets cause one login between them.

Constructing the real `FlattradeAPI` logs in to Flattrade, so the program registers a stand-in module under `stock_brokers.api.flattrade`. Each construction of the stand-in counts as a login and issues the next numbered token, `_current_login` answers from a shared record standing in for the Redis `last_login` hash, and `post` answers the UserDetails call with `Ok`.

Notice that each login is followed by a UserDetails check, and that the second request with the same stale token makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/flattrade/FlattradeSession/example_1_confirming_each_login.py
"""

import logging
import sys
import types

from stock_brokers.websockets.flattrade import (
    FlattradeSession,
)


class LoginRecord:
    """The Flattrade login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
        refused_logins (set): The login numbers whose session UserDetails refuses.
    """

    access_token = None
    login_count = 0
    refused_logins = set()


class StandInFlattradeAPI:
    """A stand-in for `FlattradeAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'flattrade-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'username': 'FT012345',
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

    def post(self, url, timeout):
        """Answers the UserDetails call the session confirms every login with.

        Args:
            url (str): The endpoint the session calls.
            timeout (int): The request timeout in seconds.

        Returns:
            dict: What the real class returns, with Noren's answer under `data`.
        """
        status = 'Ok'
        if LoginRecord.login_count in LoginRecord.refused_logins:
            status = 'Not_Ok'
        print(f'UserDetails called for {LoginRecord.access_token}: {status}')
        return {
            'data': {
                'stat': status,
                'uname': 'EXAMPLE USER',
            },
        }


class ConfirmingEachLoginExample:
    """Builds a Flattrade session and asks it to log in again twice with the same token.

    Attributes:
        session (FlattradeSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.flattrade')
        api_module.FlattradeAPI = StandInFlattradeAPI
        sys.modules['stock_brokers.api.flattrade'] = api_module
        self.session = FlattradeSession(logging.getLogger('flattrade.session'))

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
    ConfirmingEachLoginExample().run()
