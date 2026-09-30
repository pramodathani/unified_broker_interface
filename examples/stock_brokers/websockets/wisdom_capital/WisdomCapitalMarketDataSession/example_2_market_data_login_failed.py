"""Shows `WisdomCapitalMarketDataSession` raising the market data login failure the API recorded.

`WisdomCapitalAPI` establishes both XTS sessions when it is constructed, and records a failed market data login in `market_data_session_error` rather than raising it, because the interactive session may still work. `WisdomCapitalMarketDataSession` needs the market data session, so its constructor raises that recorded error, and the quotes script exits instead of connecting without a token.

Constructing the real `WisdomCapitalAPI` logs in to both XTS applications, so the program registers a stand-in module under `stock_brokers.api.wisdom_capital` whose market data login is scripted to fail.

Notice that the stand-in's login itself succeeds, and that the error comes from building the session.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalMarketDataSession/example_2_market_data_login_failed.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.wisdom_capital import (
    WisdomCapitalMarketDataSession,
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


class MarketDataLoginFailedExample:
    """Builds a market data session whose login failed.

    Attributes:
        logger (logging.Logger): Where the session would report.
    """

    def __init__(self):
        """Registers the stand-in API module and scripts the market data login to fail.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.wisdom_capital')
        api_module.WisdomCapitalAPI = StandInWisdomCapitalAPI
        sys.modules['stock_brokers.api.wisdom_capital'] = api_module
        LoginRecord.market_data_fails = True
        self.logger = logging.getLogger('wisdom_capital.session')

    def run(self):
        """Builds the session and prints the error, or the session when it builds.

        Returns:
            None: This method returns nothing.
        """
        try:
            session = WisdomCapitalMarketDataSession(self.logger)
            print(f'Market data session: {session.market_data()}')
        except RuntimeError as error:
            print(f'The market data session could not start: {error}')


if __name__ == '__main__':
    MarketDataLoginFailedExample().run()
