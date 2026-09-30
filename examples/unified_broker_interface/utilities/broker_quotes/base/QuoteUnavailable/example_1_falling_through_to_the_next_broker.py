"""Shows how `QuoteUnavailable` lets a caller fall through from one broker to the next until one has a quote.

`QuoteUnavailable` means a broker answered, or could have, but has no usable quote for the instrument: the broker does not carry its segment, does not know its token, or sent an empty answer. It is not a fault with the session, so the right response is to ask the next broker. The project's quote service does exactly that, and this program does the same by hand.

The instrument is an MCX crude oil option. INDmoney does not serve MCX and Dhan has a quote segment for it, but the stand-in Dhan client answers with an empty body, as Dhan does for a contract it holds no quote for. The stand-in Kite client then answers with a quote. None of the three sends anything over the network.

In the output, notice that each broker's `QuoteUnavailable` message says why that broker could not help, and that the loop stops at the first broker that returns a tick.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/base/QuoteUnavailable/example_1_falling_through_to_the_next_broker.py
"""

from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.dhan import (
    DhanQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.indmoney import (
    IndmoneyQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.zerodha import (
    ZerodhaQuoteSource,
)


class EmptyDhanClient:
    """A stand-in for Dhan's API client that answers every quote request with no quote."""

    def __init__(self):
        """Builds the stand-in with a made-up account.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'client_id': '1100012345',
        }

    def _current_login(self):
        """The stored login, as the real client reads it before every request.

        Returns:
            dict: The login, holding a made-up access token.
        """
        return {
            'access_token': 'example-access-token',
        }

    def post(self, url, json=None, headers=None, timeout=None):
        """Answers with Dhan's body for a request it holds no quote for.

        Args:
            url (str): The endpoint asked.
            json (dict): The request body.
            headers (dict): The request headers.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope with an empty quote object.
        """
        return {
            'data': {
                'status': 'success',
                'data': {},
            },
        }


class AnsweringKiteClient:
    """A stand-in for Zerodha's API client that answers with a quote for the crude oil option."""

    def get(self, url, params=None, timeout=None):
        """Answers with Kite's quote for the instrument token asked.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters, whose `i` is the instrument token.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding the quote keyed by instrument token.
        """
        return {
            'data': {
                params['i']: {
                    'last_price': 143.5,
                    'volume': 1802,
                    'ohlc': {
                        'open': 150.0,
                        'high': 156.2,
                        'low': 139.0,
                        'close': 148.1,
                    },
                },
            },
        }


class FallingThroughExample:
    """Asks three brokers in turn for one quote and stops at the first that has it.

    Attributes:
        brokers (list): Tuples of (quote source, stand-in client, handle), in the order they are asked.
    """

    def __init__(self):
        """Builds the three sources with their stand-in clients and handles.

        Returns:
            None: This method returns nothing.
        """
        self.brokers = [
            (
                IndmoneyQuoteSource(),
                None,
                {
                    'broker_token': '467421',
                },
            ),
            (
                DhanQuoteSource(),
                EmptyDhanClient(),
                {
                    'broker_token': '467421',
                },
            ),
            (
                ZerodhaQuoteSource(),
                AnsweringKiteClient(),
                {
                    'broker_token': '118366727',
                },
            ),
        ]

    def run(self):
        """Prints each broker's outcome and the price finally obtained.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'instrument_id': '33333333-3333-5333-8333-000000000002',
            'exchange': 'mcx',
            'segment': 'mcx_commodity_options',
            'shape': 'option',
        }
        for source, client, handle in self.brokers:
            try:
                tick = source.fetch(client, handle, identity, 1789446605.0)
            except QuoteUnavailable as error:
                print(f'{source.BROKER_NAME}: QuoteUnavailable: {error}')
                continue
            print(f'{source.BROKER_NAME}: last price {tick["last_price"]} for token {tick["instrument_token"]}')
            break


if __name__ == '__main__':
    FallingThroughExample().run()
