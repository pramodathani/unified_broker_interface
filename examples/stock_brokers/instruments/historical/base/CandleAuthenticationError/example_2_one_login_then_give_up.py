"""Logs in again once after a `CandleAuthenticationError`, and gives up when the fresh session is refused as well.

The candle download's rule for a refused session is one login, then the same window again. If the fresh session is refused too, the error goes back up and the broker is stopped, because logging in over and over is how a broker account gets locked. This program writes that rule as a small class, `OneLoginPolicy`, and runs it against two stand-in brokers: one that accepts the new token and one that refuses every token.

The stand-in login only counts how often it was called; nothing logs in anywhere.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleAuthenticationError/example_2_one_login_then_give_up.py
"""

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
)


class StandInBroker:
    """A stand-in broker that refuses the old token, and optionally every token.

    Attributes:
        refuses_every_token (bool): Whether even a fresh token is refused.
        current_token (str): The token requests are sent with.
        logins (int): How many logins have been made.
    """

    def __init__(self, refuses_every_token):
        """Builds the broker with an expired token in hand.

        Args:
            refuses_every_token (bool): Whether even a fresh token is refused.

        Returns:
            None: This method returns nothing.
        """
        self.refuses_every_token = refuses_every_token
        self.current_token = 'expired'
        self.logins = 0

    def log_in(self):
        """Pretends to log in, issuing a fresh token.

        Returns:
            None: This method returns nothing.
        """
        self.logins += 1
        self.current_token = f'fresh-{self.logins}'

    def fetch(self, token):
        """Fetches one window of candles.

        Args:
            token (str): The instrument token.

        Returns:
            str: A description of the candles received.

        Raises:
            CandleAuthenticationError: When the token in hand is refused.
        """
        if self.refuses_every_token or self.current_token == 'expired':
            raise CandleAuthenticationError(f'token {self.current_token} refused')
        return f'375 candles for {token}'


class OneLoginPolicy:
    """Fetches a window, logging in once if the session is refused.

    Attributes:
        broker (StandInBroker): The broker to fetch from.
    """

    def __init__(self, broker):
        """Wraps a broker.

        Args:
            broker (StandInBroker): The broker to fetch from.

        Returns:
            None: This method returns nothing.
        """
        self.broker = broker

    def fetch(self, token):
        """Fetches one window, with at most one login in between.

        Args:
            token (str): The instrument token.

        Returns:
            str: A description of the candles received.

        Raises:
            CandleAuthenticationError: When the session is refused even after one login.
        """
        try:
            return self.broker.fetch(token)
        except CandleAuthenticationError as error:
            print(f'  refused ({error}); logging in once')
            self.broker.log_in()
        return self.broker.fetch(token)


class OneLoginThenGiveUpExample:
    """Runs the policy against a broker that recovers and one that does not."""

    def run(self):
        """Prints what happens with each broker.

        Returns:
            None: This method returns nothing.
        """
        for refuses_every_token in (
            False,
            True,
        ):
            broker = StandInBroker(refuses_every_token)
            print(f'Broker that refuses every token: {refuses_every_token}')
            try:
                print(f'  {OneLoginPolicy(broker).fetch("738561")}')
            except CandleAuthenticationError as error:
                print(f'  giving up and stopping the broker: {error}')
            print(f'  logins made: {broker.logins}')


if __name__ == '__main__':
    OneLoginThenGiveUpExample().run()
