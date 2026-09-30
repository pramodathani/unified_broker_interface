"""Fetches Kotak Neo's quote for the Nifty 50 index, which Kotak wants by name, and shows what else Kotak refuses.

Kotak addresses most instruments by token, but its quote endpoint answers an NSE index token such as `nse_cm|26000` with 400 "Invalid neosymbol values" and wants the index's name instead, `nse_cm|Nifty 50`. `KotakQuoteSource` knows the names of the four NSE indices Kotak lists and asks for those. The tick still carries the token, `nse_cm|26000`, because that is what the mapping stores. An index quote from Kotak carries zeros for every quantity, so the tick stops at the prices.

An NSE index token outside those four has no known name, so `fetch` raises `QuoteUnavailable` before sending anything. Kotak's refusals are then classified: a 401 "unauthorised" means the session is dead, while a 424 for an invalid consumer key does not, because the key comes from the settings and no login changes it.

As in the first program, the Kotak quote module's `requests` name is replaced by a stand-in class, because the module calls the `requests` library directly. The API client is a stand-in too. Nothing leaves the process. The instant stamped on the tick is fixed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/kotak/KotakQuoteSource/example_2_nifty_index_by_name.py
"""

import datetime
import json

from stock_brokers.api.kotak import (
    KotakAPIException,
)
from unified_broker_interface.utilities.broker_quotes import kotak as kotak_quotes
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.kotak import (
    KotakQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedKotakResponse:
    """A stand-in for the `requests` response Kotak's quote endpoint returns.

    Attributes:
        status_code (int): The HTTP status.
        text (str): The body as text.
    """

    def __init__(self, status_code, payload):
        """Holds one recorded answer.

        Args:
            status_code (int): The HTTP status.
            payload (dict): The decoded JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        """The decoded JSON body.

        Returns:
            dict: The body.
        """
        return self._payload


class RecordedKotakIndexServer:
    """A stand-in for the `requests` module that answers Kotak's quote endpoint for the Nifty 50 index.

    Attributes:
        urls (list): The URL of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        """Answers a quote request with Kotak's quote for the Nifty 50 index.

        Args:
            url (str): The quote URL, ending in the neosymbol.
            headers (dict): The request headers.
            timeout (float): How long the caller would wait.

        Returns:
            RecordedKotakResponse: The recorded answer.
        """
        self.urls.append(url)
        return RecordedKotakResponse(200, {
            'data': [
                {
                    'exchange_token': 'Nifty 50',
                    'display_symbol': 'Nifty 50',
                    'exchange': 'nse_cm',
                    'ltp': '25114.0500',
                    'last_traded_quantity': '0',
                    'total_buy': '0',
                    'total_sell': '0',
                    'last_volume': '0',
                    'change': '89.3500',
                    'per_change': '0.36',
                    'ohlc': {
                        'open': '25051.2000',
                        'high': '25139.8000',
                        'low': '25030.6500',
                        'close': '25114.0500',
                    },
                },
            ],
        })


class StandInKotakClient:
    """A stand-in for Kotak's API client, holding a made-up consumer key, session and assigned host."""

    def __init__(self):
        """Builds the stand-in with made-up settings.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'api_key': 'example-consumer-key',
        }

    def _current_login(self):
        """The stored login, as the real client reads it before every request.

        Returns:
            dict: The login, holding a made-up access token and session id.
        """
        return {
            'access_token': 'example-access-token',
            'sid': 'example-session-id',
        }

    def url(self, path):
        """Builds the absolute URL on the host this session was assigned.

        Args:
            path (str): The path part.

        Returns:
            str: The absolute URL.
        """
        return f'https://e21.kotaksecurities.com{path}'


class NiftyIndexByNameExample:
    """Fetches the Nifty 50 index from Kotak, asks for an unnamed index, and classifies two refusals.

    Attributes:
        source (KotakQuoteSource): The quote source being shown.
        client (StandInKotakClient): The stand-in API client.
        server (RecordedKotakIndexServer): The stand-in for the `requests` module.
    """

    def __init__(self):
        """Builds the source and its stand-ins, and points the Kotak quote module at the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        self.source = KotakQuoteSource()
        self.client = StandInKotakClient()
        self.server = RecordedKotakIndexServer()
        kotak_quotes.requests = self.server

    def run(self):
        """Prints the index tick, what the unnamed index raises, and each refusal's classification.

        Returns:
            None: This method returns nothing.
        """
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        identity = {
            'instrument_id': '66666666-6666-5666-8666-000000000001',
            'exchange': 'nse',
            'segment': 'nse_equity_indices',
            'shape': 'security',
        }
        named_index_handle = {
            'broker_token': '26000',
        }
        unnamed_index_handle = {
            'broker_token': '26017',
        }
        tick = self.source.fetch(self.client, named_index_handle, identity, received_at)
        print(f'Requests sent: {self.server.urls}')
        print(json.dumps(tick, indent=4))
        try:
            self.source.fetch(self.client, unnamed_index_handle, identity, received_at)
        except QuoteUnavailable as error:
            print(f'QuoteUnavailable: {error}')
        print(f'Requests sent in all: {len(self.server.urls)}')
        refusals = [
            KotakAPIException(code=401, message='{"message": "unauthorised"}'),
            KotakAPIException(code=424, message='{"message": "Consumer key example-consumer-key is invalid"}'),
        ]
        for refusal in refusals:
            print(f'{refusal.args} -> log in again: {self.source.is_authentication_error(refusal)}')


if __name__ == '__main__':
    NiftyIndexByNameExample().run()
