"""Logs in to Kotak again unconditionally, as the order update socket does after a refusal.

The order update socket calls `KotakSession.log_in_again_without_checking` when Kotak refuses its connection frame. That logs in even when another process has already replaced the session, unlike `log_in_again`, which would skip the login in that case.

Constructing the real `KotakAPI` logs in to Kotak, so the program registers a stand-in module under `stock_brokers.api.kotak` whose constructions count as logins. It replaces the session as another process would, shows that `log_in_again` with the old session id does nothing, and then calls `log_in_again_without_checking`.

Notice that only the unconditional call makes a login.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakSession/example_2_logging_in_without_checking.py
"""

import logging
import sys
import types

from stock_brokers.websockets.kotak import (
    KotakSession,
)


class LoginRecord:
    """The Kotak login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The access token in force now.
        session_id (str | None): The session id in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    session_id = None
    login_count = 0


class StandInKotakAPI:
    """A stand-in for `KotakAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered access token and session id.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'kotak-token-{LoginRecord.login_count}'
        LoginRecord.session_id = f'kotak-sid-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, session id and host, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
            'sid': LoginRecord.session_id,
            'base_url': 'https://e21.kotaksecurities.com/',
        }


class LoggingInWithoutCheckingExample:
    """Compares the checked and unchecked logins of a Kotak session.

    Attributes:
        session (KotakSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.kotak')
        api_module.KotakAPI = StandInKotakAPI
        sys.modules['stock_brokers.api.kotak'] = api_module
        self.session = KotakSession(logging.getLogger('kotak.session'))

    def run(self):
        """Replaces the session elsewhere, then tries both kinds of login.

        Returns:
            None: This method returns nothing.
        """
        first_session_id = self.session.credentials()[1]
        LoginRecord.session_id = 'kotak-sid-from-another-process'
        print(f'Another process replaced {first_session_id}.')
        self.session.log_in_again(first_session_id)
        print(f'After log_in_again: {self.session.credentials()}')
        self.session.log_in_again_without_checking()
        print(f'After log_in_again_without_checking: {self.session.credentials()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInWithoutCheckingExample().run()
