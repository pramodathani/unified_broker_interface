"""Logs a Stoxkart session in again and shows the new token in its headers.

`StoxkartSession.log_in_again` logs in by constructing `StoxkartAPI` again. Unlike the other brokers' sessions it has no check for a token another process already replaced and no lock, because only the order socket uses it, and that socket calls it only after Stoxkart refused the token.

Constructing the real `StoxkartAPI` logs in to Stoxkart, so the program registers a stand-in module under `stock_brokers.api.stoxkart` whose constructions count as logins.

Notice the second login and the new `x-access-token`.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartSession/example_2_logging_in_again.py
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


class LoggingInAgainExample:
    """Logs a Stoxkart session in again.

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
        """Prints the token before and after logging in again.

        Returns:
            None: This method returns nothing.
        """
        print(f"Token before: {self.session.authentication_headers()['x-access-token']}")
        self.session.log_in_again()
        print(f"Token after: {self.session.authentication_headers()['x-access-token']}")
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInAgainExample().run()
