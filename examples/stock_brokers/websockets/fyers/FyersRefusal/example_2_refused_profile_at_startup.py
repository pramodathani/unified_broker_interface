"""Catches the `FyersRefusal` a Fyers session raises when the profile refuses its very first login.

`FyersSession` confirms its first login against the profile endpoint while it is being built, so a session Fyers refuses never reaches a socket: the constructor raises `FyersRefusal`. A broker script builds its session before its sockets, so this is the error it sees and exits on when the stored login is dead and a fresh one is refused.

Constructing the real `FyersAPI` logs in to Fyers, so the program registers a stand-in module under `stock_brokers.api.fyers` whose first login is scripted to have its profile refused with code -16.

Notice that the refusal carries the profile's code and a message quoting Fyers' answer.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersRefusal/example_2_refused_profile_at_startup.py
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


class RefusedProfileAtStartupExample:
    """Builds a Fyers session whose first profile check is refused.

    Attributes:
        logger (logging.Logger): Where the session would report.
    """

    def __init__(self):
        """Registers the stand-in API module and scripts the first profile to be refused.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StandInFyersAPI
        sys.modules['stock_brokers.api.fyers'] = api_module
        LoginRecord.refused_profiles = {
            1,
        }
        self.logger = logging.getLogger('fyers.session')

    def run(self):
        """Builds the session and prints the refusal it raises.

        Returns:
            None: This method returns nothing.
        """
        try:
            FyersSession(self.logger)
        except FyersRefusal as refusal:
            print(f'The session could not start: code={refusal.code}')
            print(f'Message: {refusal.message}')


if __name__ == '__main__':
    RefusedProfileAtStartupExample().run()
