"""Logs in to Flattrade again without checking and shows the error raised when UserDetails refuses the new session.

`FlattradeSession.log_in_again_without_checking` is what the order update socket calls after a refusal: it logs in whether or not the token was already replaced, then confirms the new session against UserDetails. If Noren refuses that session, the session raises `RuntimeError` with Noren's answer, which the socket's reconnect loop treats as a login that failed, so the socket gives up and its script exits for systemd to restart.

Constructing the real `FlattradeAPI` logs in to Flattrade, so the program registers a stand-in module under `stock_brokers.api.flattrade` whose second login is scripted to be refused by the pretend UserDetails call.

Notice that the first login is confirmed, that the second one is made even though nothing was refused, and that the `RuntimeError` carries Noren's `Not_Ok` answer.

Run it from the project root:

    python examples/stock_brokers/websockets/flattrade/FlattradeSession/example_2_userdetails_refuses_the_new_session.py
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


class UserdetailsRefusesTheNewSessionExample:
    """Logs in again unconditionally and catches the refusal of the new session.

    Attributes:
        session (FlattradeSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module, scripts the second login to be refused, and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.flattrade')
        api_module.FlattradeAPI = StandInFlattradeAPI
        sys.modules['stock_brokers.api.flattrade'] = api_module
        LoginRecord.refused_logins = {
            2,
        }
        self.session = FlattradeSession(logging.getLogger('flattrade.session'))

    def run(self):
        """Logs in again without checking and prints the error.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.session.log_in_again_without_checking()
        except RuntimeError as error:
            print(f'RuntimeError: {error}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    UserdetailsRefusesTheNewSessionExample().run()
