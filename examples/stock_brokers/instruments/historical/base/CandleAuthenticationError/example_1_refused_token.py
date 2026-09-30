"""Raises `CandleAuthenticationError` when a broker refuses the session, keeping the broker's own error as its cause.

A refused session is not a fault of the series being fetched, and nothing else will work until the session is fixed, so the candle download treats this failure as a reason to log in again once, and to stop the broker if that does not help. A broker module raises it from `fetch_candles` when the broker's answer says the token is no good.

This program has a stand-in broker client that fails the way Kite's client does, with an exception named `TokenException`. A small fetcher raises `CandleAuthenticationError` from it with `raise ... from`, so the original exception stays attached as `__cause__` for the log. No broker is contacted.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleAuthenticationError/example_1_refused_token.py
"""

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
    CandleError,
)


class TokenException(Exception):
    """The stand-in broker client's error for a token it does not accept."""


class StandInBrokerClient:
    """A stand-in for a broker client whose stored token has expired."""

    def historical_data(self, token):
        """Refuses every request, as a broker does with an expired token.

        Args:
            token (str): The instrument token.

        Returns:
            dict: Never returns.

        Raises:
            TokenException: Always.
        """
        raise TokenException(f'Incorrect `api_key` or `access_token` while fetching {token}.')


class SessionAwareFetcher:
    """Fetches candles and raises `CandleAuthenticationError` when the session is refused.

    Attributes:
        client (StandInBrokerClient): The broker client.
    """

    def __init__(self, client):
        """Wraps a broker client.

        Args:
            client (StandInBrokerClient): The broker client.

        Returns:
            None: This method returns nothing.
        """
        self.client = client

    def fetch(self, token):
        """Fetches one window of candles.

        Args:
            token (str): The instrument token.

        Returns:
            dict: The broker's answer.

        Raises:
            CandleAuthenticationError: When the broker refuses the session.
        """
        try:
            return self.client.historical_data(token)
        except TokenException as error:
            raise CandleAuthenticationError(str(error)) from error


class RefusedTokenExample:
    """Fetches with an expired token and prints the failure it produces.

    Attributes:
        fetcher (SessionAwareFetcher): The fetcher being shown.
    """

    def __init__(self):
        """Builds the fetcher around the stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.fetcher = SessionAwareFetcher(StandInBrokerClient())

    def run(self):
        """Fetches once and prints the failure, its cause and its place in the hierarchy.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.fetcher.fetch('738561')
        except CandleAuthenticationError as error:
            print(f'CandleAuthenticationError: {error}')
            print(f'Caused by: {type(error.__cause__).__name__}')
            print(f'It is a CandleError: {isinstance(error, CandleError)}')


if __name__ == '__main__':
    RefusedTokenExample().run()
