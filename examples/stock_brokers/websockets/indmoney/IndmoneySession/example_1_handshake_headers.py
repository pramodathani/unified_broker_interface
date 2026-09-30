"""Builds the handshake headers an INDmoney socket presents and logs in again only when the failed token is still current.

`IndmoneySession` holds one `INDMoneyAPI` and reads the login afresh whenever a socket connects. `credentials` returns the client id and the token in force, and `handshake_headers` turns them into the headers INDstocks expects in the websocket handshake: the token as `Authorization` and the client id as `x-api-key`. When a quotes socket is refused, `log_in_again` logs in only if the token it used is still the one in force.

Constructing the real `INDMoneyAPI` logs in to INDmoney, so the program registers a stand-in module under `stock_brokers.api.indmoney`. Each construction of the stand-in counts as one login and issues the next numbered token, and `_current_login` answers from a shared record standing in for the Redis `last_login` hash.

Notice that the headers change after the login, and that the second request with the stale token makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/indmoney/IndmoneySession/example_1_handshake_headers.py
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
            'client_id': 'ind-client-7',
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


class HandshakeHeadersExample:
    """Prints an INDmoney session's credentials and handshake headers around a login.

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
        """Prints the headers, logs in again twice with the same stale token, and prints them again.

        Returns:
            None: This method returns nothing.
        """
        client_id, failed_token = self.session.credentials()
        print(f'Credentials: client_id={client_id} access_token={failed_token}')
        headers, token = self.session.handshake_headers()
        print(f'Handshake headers: {headers} for token {token}')
        self.session.log_in_again(failed_token)
        self.session.log_in_again(failed_token)
        headers, token = self.session.handshake_headers()
        print(f'Handshake headers: {headers} for token {token}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    HandshakeHeadersExample().run()
