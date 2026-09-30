"""Shows the handshake headers without a client id, and a login made without checking the token.

An INDmoney account whose settings have no client id presents only the `Authorization` header, because `handshake_headers` adds `x-api-key` only when there is a client id. The order update socket logs in again with `log_in_again_without_checking`, which logs in even when another process already replaced the token that failed.

Constructing the real `INDMoneyAPI` logs in to INDmoney, so the program registers a stand-in module under `stock_brokers.api.indmoney` whose settings hold no client id and whose constructions count as logins. The program replaces the token as another process would before logging in.

Notice that the headers hold `Authorization` alone, and that the unconditional login replaces the other process's token.

Run it from the project root:

    python examples/stock_brokers/websockets/indmoney/IndmoneySession/example_2_no_client_id_and_unchecked_login.py
"""

import logging
import sys
import types

from stock_brokers.websockets.indmoney import (
    IndmoneySession,
)


class LoginRecord:
    """The INDmoney login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInINDMoneyAPI:
    """A stand-in for `INDMoneyAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'indmoney-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'client_id': None,
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


class NoClientIdAndUncheckedLoginExample:
    """Prints headers without a client id and logs in again unconditionally.

    Attributes:
        session (IndmoneySession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.indmoney')
        api_module.INDMoneyAPI = StandInINDMoneyAPI
        sys.modules['stock_brokers.api.indmoney'] = api_module
        self.session = IndmoneySession(logging.getLogger('indmoney.session'))

    def run(self):
        """Prints the headers, replaces the token elsewhere, and logs in without checking.

        Returns:
            None: This method returns nothing.
        """
        headers, token = self.session.handshake_headers()
        print(f'Handshake headers: {headers}')
        LoginRecord.access_token = 'indmoney-token-from-another-process'
        print(f'Another process replaced {token}.')
        self.session.log_in_again_without_checking()
        print(f'Credentials now: {self.session.credentials()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    NoClientIdAndUncheckedLoginExample().run()
