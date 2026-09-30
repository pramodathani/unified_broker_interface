"""Shows `SessionUnavailable` being raised when a broker refuses the session and no newer session has been stored yet.

When a broker refuses a quote request because the session is dead, the quote service calls `relogin`. It compares the session the request was sent with, read beforehand by `session_marker`, with the session stored now. If nothing newer is stored, it asks for the broker's login service to be started and raises `SessionUnavailable`, so this broker fails this one request and the quote falls through to the next broker. The exception is a plain `Exception` subclass whose message is all it carries.

For a real broker, `relogin` would run `systemctl --user start <broker>-login.service`. This program uses the made-up broker name `paper_broker`, which has no login unit, so nothing is started: `relogin` only logs a warning to standard error and raises. The exception's message still says the login has been started, because its text is the same whatever `relogin` managed to do. The API client is a stand-in class whose stored login never changes. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/clients/SessionUnavailable/example_1_no_newer_session_stored.py
"""

from unified_broker_interface.utilities.broker_quotes.utilities import clients
from unified_broker_interface.utilities.broker_quotes.utilities.clients import (
    SessionUnavailable,
)


class UnchangingLoginClient:
    """A stand-in for a broker API client whose stored login stays the same."""

    def _current_login(self):
        """The stored login, as the real client reads it before every request.

        Returns:
            dict: The login, holding a made-up token and the time it was issued.
        """
        return {
            'access_token': 'token-issued-at-seven',
            'last_login': '2026-09-15 07:00:04',
        }


class NoNewerSessionStoredExample:
    """Asks `relogin` about a refused request when no newer session exists, and catches what it raises.

    Attributes:
        client (UnchangingLoginClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.client = UnchangingLoginClient()

    def run(self):
        """Prints the session the request was sent with and the caught exception.

        Returns:
            None: This method returns nothing.
        """
        refused_session = clients.session_marker(self.client)
        print(f'Request sent with session: {refused_session}')
        try:
            clients.relogin('paper_broker', self.client, refused_session)
        except SessionUnavailable as error:
            print(f'Caught: {type(error).__name__}')
            print(f'Message: {error}')
            print(f'Arguments: {error.args}')


if __name__ == '__main__':
    NoNewerSessionStoredExample().run()
