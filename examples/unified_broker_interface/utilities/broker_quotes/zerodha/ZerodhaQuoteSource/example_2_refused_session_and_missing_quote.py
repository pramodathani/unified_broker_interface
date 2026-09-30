"""Shows the two ways a Zerodha quote can fail, and which of them the quote service answers by logging in again.

When Kite refuses the access token, the API client raises a `ZerodhaAPIException` whose text names Kite's `TokenException`. `fetch` lets that exception through, and `is_authentication_error` recognises it, so the quote service knows that a fresh login is the remedy. When Kite answers but holds no quote for the token, as for an expired contract, `fetch` raises `QuoteUnavailable` instead, which is not an authentication error, so the service just moves on to the next broker.

Two stand-in API clients play the two answers: one raises the exception the real client raises for Kite's HTTP 403 body, and the other answers with an empty `data` object. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/zerodha/ZerodhaQuoteSource/example_2_refused_session_and_missing_quote.py
"""

from stock_brokers.api.zerodha import (
    ZerodhaAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.zerodha import (
    ZerodhaQuoteSource,
)


class RefusingKiteClient:
    """A stand-in for Zerodha's API client whose session Kite no longer accepts."""

    def get(self, url, params=None, timeout=None):
        """Refuses the request the way the real client does for Kite's HTTP 403.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters.
            timeout (float): How long the caller would wait.

        Returns:
            dict: Never returns.

        Raises:
            ZerodhaAPIException: Always, carrying Kite's error type and message.
        """
        raise ZerodhaAPIException(code='TokenException', message='Incorrect `api_key` or `access_token`.')


class EmptyKiteClient:
    """A stand-in for Zerodha's API client whose quote answer holds nothing for the token asked."""

    def get(self, url, params=None, timeout=None):
        """Answers with Kite's empty quote object.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope with an empty `data` object.
        """
        return {
            'status': 'success',
            'code': 200,
            'data': {},
        }


class RefusedSessionAndMissingQuoteExample:
    """Fetches one quote through each failing client and classifies what was raised.

    Attributes:
        source (ZerodhaQuoteSource): The quote source being shown.
        clients (list): Pairs of (label, stand-in client).
    """

    def __init__(self):
        """Builds the source and the two failing clients.

        Returns:
            None: This method returns nothing.
        """
        self.source = ZerodhaQuoteSource()
        self.clients = [
            (
                'refused session',
                RefusingKiteClient(),
            ),
            (
                'expired contract',
                EmptyKiteClient(),
            ),
        ]

    def run(self):
        """Prints what each fetch raised and whether logging in again would help.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '12345678',
            'order_symbol': 'NIFTY26AUG24000CE',
            'lot_size': '75',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000004',
            'exchange': 'nse',
            'segment': 'nse_equity_index_options',
            'shape': 'option',
        }
        for label, client in self.clients:
            try:
                self.source.fetch(client, handle, identity, 1789446605.0)
            except (QuoteUnavailable, ZerodhaAPIException) as error:
                print(f'{label}: {type(error).__name__}: {error}')
                print(f'    log in again: {self.source.is_authentication_error(error)}')


if __name__ == '__main__':
    RefusedSessionAndMissingQuoteExample().run()
