"""Reads the interactive token Wisdom Capital processes share and the user id inside it, then checks the login again.

`WisdomCapitalInteractiveSession` joins with the interactive token every Wisdom Capital process shares through `last_login`. `current_token` returns that token, `shared_login` returns it together with the `userID` claim of its JWT payload, which XTS wants in the connection query, and `log_in_again_without_checking` constructs `WisdomCapitalAPI` again, which keeps a stored token that still works and logs in only when it does not.

Constructing the real `WisdomCapitalAPI` logs in to both XTS applications, so the program registers a stand-in module under `stock_brokers.api.wisdom_capital` whose tokens are JWTs carrying the user id. Each construction counts as one login.

Notice that the user id is read from inside the token, and that the token changes after the login check.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalInteractiveSession/example_1_shared_login_and_user_id.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.wisdom_capital import (
    WisdomCapitalInteractiveSession,
)


class LoginRecord:
    """The Wisdom Capital login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        market_data_token (str | None): The market data token in force now.
        interactive_user_id (str | None): The user id inside the interactive token in force now.
        interactive_session (str | None): The session inside the interactive token in force now.
        login_count (int): How many interactive logins the stand-in API has made.
        market_data_logins (int): How many market data logins the stand-in API has made.
        market_data_fails (bool): Whether the market data login fails.
    """

    market_data_token = None
    interactive_user_id = 'WC0001'
    interactive_session = None
    login_count = 0
    market_data_logins = 0
    market_data_fails = False


class StandInWisdomCapitalAPI:
    """A stand-in for `WisdomCapitalAPI` whose construction is a pretend login to both XTS applications.

    Attributes:
        market_data_session_error (Exception | None): The market data login failure, recorded rather than raised, as the real class does.
    """

    def __init__(self):
        """Logs in, which here only issues numbered tokens.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.interactive_session = f'interactive-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self.market_data_session_error = None
        if LoginRecord.market_data_fails:
            self.market_data_session_error = RuntimeError('the market data login was refused: Invalid secret key')
        elif LoginRecord.market_data_token is None:
            self.log_in_to_market_data()

    def log_in_to_market_data(self):
        """Issues the next numbered market data token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.market_data_logins = LoginRecord.market_data_logins + 1
        LoginRecord.market_data_token = f'market-data-token-{LoginRecord.market_data_logins}'

    def _current_login(self):
        """The interactive login in force now, its token a JWT carrying the user id as XTS signs it.

        Returns:
            dict: The access token.
        """
        if LoginRecord.interactive_session is None:
            return {
                'access_token': None,
            }
        claims = {
            'session': LoginRecord.interactive_session,
        }
        if LoginRecord.interactive_user_id is not None:
            claims['userID'] = LoginRecord.interactive_user_id
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        return {
            'access_token': f'header.{payload}.signature',
        }

    def market_data_session(self):
        """The market data token and user id in force now.

        Returns:
            dict: `access_token` and `user_id`.
        """
        return {
            'access_token': LoginRecord.market_data_token,
            'user_id': 'WCMD01',
        }

    def replace_market_data_session(self, stale_access_token=None):
        """Logs in to market data again, unless the token in force is no longer the stale one.

        Args:
            stale_access_token (str | None): The token that was refused.

        Returns:
            dict: The market data session now in force.
        """
        if LoginRecord.market_data_token == stale_access_token:
            self.log_in_to_market_data()
            print(f'Stand-in market data login issued {LoginRecord.market_data_token}')
        else:
            print('The market data token was already replaced; no login.')
        return self.market_data_session()


class SharedLoginAndUserIdExample:
    """Reads the shared interactive login around a login check.

    Attributes:
        session (WisdomCapitalInteractiveSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.wisdom_capital')
        api_module.WisdomCapitalAPI = StandInWisdomCapitalAPI
        sys.modules['stock_brokers.api.wisdom_capital'] = api_module
        self.session = WisdomCapitalInteractiveSession(logging.getLogger('wisdom_capital.session'))

    def claims(self, token):
        """The JWT claims of a token, decoded for display.

        Args:
            token (str): The token.

        Returns:
            dict: The claims.
        """
        payload = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))

    def run(self):
        """Prints the shared login before and after a login check.

        Returns:
            None: This method returns nothing.
        """
        token, user_id = self.session.shared_login()
        print(f'User id {user_id}, token claims {self.claims(token)}')
        self.session.log_in_again_without_checking()
        print(f'Token claims after the check: {self.claims(self.session.current_token())}')


if __name__ == '__main__':
    SharedLoginAndUserIdExample().run()
