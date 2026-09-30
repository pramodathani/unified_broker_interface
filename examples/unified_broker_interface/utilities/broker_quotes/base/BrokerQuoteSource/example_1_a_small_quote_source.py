"""Writes a small quote source for an imaginary broker by subclassing `BrokerQuoteSource`, and fetches one quote with it.

A broker's quote module subclasses `BrokerQuoteSource`, sets `BROKER_NAME`, and implements two methods: `fetch`, which turns the broker's quote answer into a tick in the market feeds' contract shape, and `is_authentication_error`, which tells the quote service whether a failure means the broker's session is dead. The base module's `contract_tick` builds the empty tick with all twenty keys present, so a subclass only fills in what its broker sends.

The imaginary broker here is called `paper`. Its API client is a stand-in class that answers every request with one recorded-looking INFY quote, so the program needs no network, no data store and no login. The instant stamped on the tick is fixed, so the output is the same on every run.

In the output, notice that every contract key is present even though the imaginary broker sends only a few fields, that `TIMEOUT_SECONDS` comes from the base class, and that only the session refusal counts as an authentication error.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/base/BrokerQuoteSource/example_1_a_small_quote_source.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes import base

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class PaperBrokerClient:
    """A stand-in API client for the imaginary broker, answering every quote request with one canned INFY quote.

    Attributes:
        requests (list): The parameters of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, params=None, timeout=None):
        """Answers a quote request the way a broker API client wraps a successful answer.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, with the broker's body under `data`.
        """
        self.requests.append(params)
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'INFY': {
                    'ltp': 1512.35,
                    'close': 1498.8,
                    'volume': 4312876,
                },
            },
        }


class PaperQuoteSource(base.BrokerQuoteSource):
    """Fetches quotes from the imaginary `paper` broker."""

    BROKER_NAME = 'paper'

    def fetch(self, client, handle, identity, received_at):
        """One instrument's quote from the imaginary broker as a contract tick.

        Args:
            client (PaperBrokerClient): The broker's API client.
            handle (dict): The broker's order handle for the instrument; its `order_symbol` is what the broker is asked for.
            identity (dict): The instrument's identity.
            received_at (float): The instant to stamp on the tick, in epoch seconds.

        Returns:
            dict: The contract tick.

        Raises:
            QuoteUnavailable: The broker's answer held no quote for the symbol.
        """
        symbol = handle['order_symbol']
        response = client.get(url='https://paper.example/quote', params={'symbol': symbol}, timeout=self.TIMEOUT_SECONDS)
        quote = response['data'].get(symbol)
        if quote is None:
            raise base.QuoteUnavailable(f'paper returned no quote for {symbol}')
        tick = base.contract_tick(self.BROKER_NAME, symbol, identity['exchange'], received_at)
        tick['last_price'] = quote['ltp']
        tick['volume'] = quote['volume']
        tick['ohlc']['close'] = quote['close']
        return tick

    def is_authentication_error(self, exception):
        """Whether an exception from `fetch` means the imaginary broker no longer accepts the session.

        Args:
            exception (Exception): What `fetch` raised.

        Returns:
            bool: True when the text says the session expired.
        """
        return 'session expired' in str(exception).lower()


class SmallQuoteSourceExample:
    """Fetches one quote through the imaginary broker's source and classifies two failures.

    Attributes:
        source (PaperQuoteSource): The quote source being shown.
        client (PaperBrokerClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = PaperQuoteSource()
        self.client = PaperBrokerClient()

    def run(self):
        """Prints the fetched tick and whether two failures are authentication errors.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '408065',
            'order_symbol': 'INFY',
            'lot_size': '1',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000001',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        print(f'Broker: {self.source.BROKER_NAME}, timeout: {self.source.TIMEOUT_SECONDS} seconds')
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Request sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))
        failures = [
            RuntimeError('Session expired, please log in again'),
            TimeoutError('read timed out'),
        ]
        for failure in failures:
            print(f'{failure!r} is an authentication error: {self.source.is_authentication_error(failure)}')


if __name__ == '__main__':
    SmallQuoteSourceExample().run()
