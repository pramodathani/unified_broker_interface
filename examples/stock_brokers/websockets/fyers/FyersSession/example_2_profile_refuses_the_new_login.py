"""Logs in to Fyers again without checking, and shows `FyersRefusal` when the profile refuses the new session.

`FyersSession.log_in_again_without_checking` is what the order update socket calls after a refusal: it logs in whether or not another process already replaced the token, then confirms the new session against the profile. When the profile is refused the session raises `FyersRefusal` carrying Fyers' code, and a socket's reconnect loop takes that as a failed login and gives up. Separately, `token_claims` answers an empty dictionary for a token that is not a JWT, which the sockets treat as an expired token.

Constructing the real `FyersAPI` logs in to Fyers, so the program registers a stand-in module under `stock_brokers.api.fyers` whose second login is scripted to have its profile refused with code -16.

Notice that the refusal's code and message come from the profile answer, and that a malformed token yields no claims instead of an error.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersSession/example_2_profile_refuses_the_new_login.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.fyers import (
    FyersRefusal,
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


class ProfileRefusesTheNewLoginExample:
    """Logs in again unconditionally and catches the profile's refusal.

    Attributes:
        session (FyersSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module, scripts the second profile to be refused, and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StandInFyersAPI
        sys.modules['stock_brokers.api.fyers'] = api_module
        LoginRecord.refused_profiles = {
            2,
        }
        self.session = FyersSession(logging.getLogger('fyers.session'))

    def run(self):
        """Logs in again without checking, prints the refusal, and decodes a malformed token.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.session.log_in_again_without_checking()
        except FyersRefusal as refusal:
            print(f'FyersRefusal: code={refusal.code} message={refusal.message}')
        print(f'Claims of a malformed token: {self.session.token_claims("not-a-jwt")}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    ProfileRefusesTheNewLoginExample().run()
