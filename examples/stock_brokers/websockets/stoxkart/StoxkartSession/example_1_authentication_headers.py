"""Reads the headers and client code Stoxkart's order socket authenticates with.

`StoxkartSession` holds the `StoxkartAPI` whose login authenticates the order socket. `authentication_headers` builds the headers the socket's authentication request carries, with the access token in force now, and `client_id` gives the client code the socket connects as. Both read the account's settings, which the real class loads from MongoDB.

Constructing the real `StoxkartAPI` logs in to Stoxkart, so the program registers a stand-in module under `stock_brokers.api.stoxkart` whose construction counts as a login and whose `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice that the headers pick up a token another process obtained without the session logging in.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartSession/example_1_authentication_headers.py
"""

import logging
import sys
import types

from stock_brokers.websockets.stoxkart import (
    StoxkartSession,
)


class LoginRecord:
    """The Stoxkart login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInStoxkartAPI:
    """A stand-in for `StoxkartAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'stoxkart-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'ucc_code': 'SK12345',
            'api_key': 'stoxkart-api-key',
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


class AuthenticationHeadersExample:
    """Prints a Stoxkart session's headers before and after another process logs in.

    Attributes:
        session (StoxkartSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.stoxkart')
        api_module.StoxkartAPI = StandInStoxkartAPI
        sys.modules['stock_brokers.api.stoxkart'] = api_module
        self.session = StoxkartSession()

    def run(self):
        """Prints the client code and the headers twice.

        Returns:
            None: This method returns nothing.
        """
        print(f'Client code: {self.session.client_id()}')
        print(f'Headers: {self.session.authentication_headers()}')
        LoginRecord.access_token = 'stoxkart-token-from-another-process'
        print(f'Headers after another process logged in: {self.session.authentication_headers()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    AuthenticationHeadersExample().run()
