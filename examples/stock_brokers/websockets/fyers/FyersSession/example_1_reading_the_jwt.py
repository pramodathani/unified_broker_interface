"""Reads a Fyers session's credentials and the claims inside its JWT access token, and logs in again once.

`FyersSession` holds one `FyersAPI`, confirms every login against the profile endpoint because Fyers can refuse a dead session inside an HTTP 200, and reads the login afresh on every connect. The access token is a JWT, and `token_claims` decodes its claims: the quotes socket reads `exp` to avoid sending an expired token and `hsm_key` to authenticate the market feed. `log_in_again` logs in only when the token a refused socket used is still the one in force.

Constructing the real `FyersAPI` logs in to Fyers, so the program registers a stand-in module under `stock_brokers.api.fyers`. Each construction counts as one login and issues a JWT with the next numbered hsm key, `get` serves the profile, and `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice the profile check after each login, the claims of the old and new tokens, and that the second request with the stale token makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersSession/example_1_reading_the_jwt.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.fyers import (
    FyersSession,
)


class LoginRecord:
    """The Fyers login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
        expired_logins (set): The login numbers whose token has already expired.
        refused_profiles (set): The login numbers whose session the profile endpoint refuses.
    """

    access_token = None
    login_count = 0
    expired_logins = set()
    refused_profiles = set()


class StandInFyersAPI:
    """A stand-in for `FyersAPI` whose construction is a pretend login that issues a JWT access token."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        expiry = 4102444800
        if LoginRecord.login_count in LoginRecord.expired_logins:
            expiry = 1
        claims = {
            'exp': expiry,
            'hsm_key': f'hsm-key-{LoginRecord.login_count}',
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        LoginRecord.access_token = f'header.{payload}.signature'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'app_id': 'XY1234-100',
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

    def get(self, url, timeout):
        """Answers the profile call the session confirms every login with.

        Args:
            url (str): The endpoint the session calls.
            timeout (int): The request timeout in seconds.

        Returns:
            dict: What the real class returns, with Fyers' answer under `data`.
        """
        if LoginRecord.login_count in LoginRecord.refused_profiles:
            print(f'Profile refused for login {LoginRecord.login_count}')
            return {
                'data': {
                    's': 'error',
                    'code': -16,
                    'message': 'Could not authenticate the user',
                },
            }
        print(f'Profile served for login {LoginRecord.login_count}')
        return {
            'data': {
                's': 'ok',
                'data': {
                    'fy_id': 'XY01234',
                },
            },
        }


class ReadingTheJwtExample:
    """Reads a Fyers session's token claims around a login.

    Attributes:
        session (FyersSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StandInFyersAPI
        sys.modules['stock_brokers.api.fyers'] = api_module
        self.session = FyersSession(logging.getLogger('fyers.session'))

    def run(self):
        """Prints the claims, logs in again twice with the same stale token, and prints the new claims.

        Returns:
            None: This method returns nothing.
        """
        app_id, failed_token = self.session.credentials()
        print(f'App id: {app_id}')
        print(f'Claims: {self.session.token_claims(failed_token)}')
        self.session.log_in_again(failed_token)
        self.session.log_in_again(failed_token)
        new_token = self.session.credentials()[1]
        print(f'Claims: {self.session.token_claims(new_token)}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    ReadingTheJwtExample().run()
