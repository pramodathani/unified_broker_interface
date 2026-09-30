"""Logs in to Dhan again unconditionally, as the order update socket does after a refusal.

The order update socket cannot tell which token Dhan rejected, because the rejection is a binary frame sent after its own login message, so it calls `DhanSession.log_in_again_without_checking`. That logs in even when another process has already replaced the token, unlike `log_in_again`, which would skip the login in that case.

Constructing the real `DhanAPI` logs in to Dhan, so the program registers a stand-in module under `stock_brokers.api.dhan` whose constructions count as logins. It first sets the token as another process would, shows that `log_in_again` with the old token does nothing, and then calls `log_in_again_without_checking`.

Notice that only the unconditional call makes a login, and that it replaces the other process's token with a new one.

Run it from the project root:

    python examples/stock_brokers/websockets/dhan/DhanSession/example_2_logging_in_without_checking.py
"""

import logging
import sys
import types

from stock_brokers.websockets.dhan import (
    DhanSession,
)


class LoginRecord:
    """The Dhan login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInDhanAPI:
    """A stand-in for `DhanAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'dhan-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'client_id': '1100012345',
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


class LoggingInWithoutCheckingExample:
    """Compares the checked and unchecked logins of a Dhan session.

    Attributes:
        session (DhanSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-in API module and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.dhan')
        api_module.DhanAPI = StandInDhanAPI
        sys.modules['stock_brokers.api.dhan'] = api_module
        self.session = DhanSession(logging.getLogger('dhan.session'))

    def run(self):
        """Replaces the token elsewhere, then tries both kinds of login.

        Returns:
            None: This method returns nothing.
        """
        first_token = self.session.credentials()[1]
        LoginRecord.access_token = 'dhan-token-from-another-process'
        print(f'Another process replaced {first_token}.')
        self.session.log_in_again(first_token)
        print(f'After log_in_again: {self.session.credentials()[1]}')
        self.session.log_in_again_without_checking()
        print(f'After log_in_again_without_checking: {self.session.credentials()[1]}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    LoggingInWithoutCheckingExample().run()
