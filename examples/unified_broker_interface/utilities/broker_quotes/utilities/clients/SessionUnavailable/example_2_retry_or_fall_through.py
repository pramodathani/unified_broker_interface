"""Shows the two outcomes of a refused session side by side: sending again with a newer session, or giving up on this broker with `SessionUnavailable`.

Any process can log a broker in, and every API client reads the stored login before each request. So when a broker refuses a session, another process may already have stored a newer one. `relogin` checks that first: if the stored session differs from the refused one it simply returns, and the caller sends the request once more; otherwise it asks for the broker's login and raises `SessionUnavailable`, and the caller moves on to the next broker.

This program plays both cases with a stand-in API client whose stored login can be replaced, standing in for a login by another process. It uses the made-up broker name `paper_broker`, which has no login unit, so the second case starts nothing and only logs a warning to standard error. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/clients/SessionUnavailable/example_2_retry_or_fall_through.py
"""

from unified_broker_interface.utilities.broker_quotes.utilities import clients
from unified_broker_interface.utilities.broker_quotes.utilities.clients import (
    SessionUnavailable,
)


class ReplaceableLoginClient:
    """A stand-in for a broker API client whose stored login another process may replace.

    Attributes:
        login (dict): The login currently stored.
    """

    def __init__(self):
        """Builds the stand-in holding the morning's login.

        Returns:
            None: This method returns nothing.
        """
        self.login = {
            'access_token': 'token-issued-at-seven',
            'last_login': '2026-09-15 07:00:04',
        }

    def _current_login(self):
        """The stored login, as the real client reads it before every request.

        Returns:
            dict: The login.
        """
        return self.login


class RetryOrFallThroughExample:
    """Runs `relogin` once after another process has logged in, and once when none has.

    Attributes:
        client (ReplaceableLoginClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.client = ReplaceableLoginClient()

    def decide(self, refused_session):
        """Asks `relogin` what follows a refused request and describes the answer.

        Args:
            refused_session (tuple): The session marker read before the refused request.

        Returns:
            str: What the caller should do next.
        """
        try:
            clients.relogin('paper_broker', self.client, refused_session)
        except SessionUnavailable as error:
            return f'fall through to the next broker ({error})'
        return f'send again with {clients.session_marker(self.client)}'

    def run(self):
        """Prints the decision in each of the two cases.

        Returns:
            None: This method returns nothing.
        """
        refused_session = clients.session_marker(self.client)
        self.client.login = {
            'access_token': 'token-issued-at-noon',
            'last_login': '2026-09-15 12:00:31',
        }
        print(f'Another process logged in: {self.decide(refused_session)}')
        refused_session = clients.session_marker(self.client)
        print(f'Nobody logged in since: {self.decide(refused_session)}')


if __name__ == '__main__':
    RetryOrFallThroughExample().run()
