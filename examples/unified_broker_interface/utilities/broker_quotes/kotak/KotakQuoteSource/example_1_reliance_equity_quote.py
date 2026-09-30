"""Fetches Kotak Neo's quote for RELIANCE on NSE and shows the contract tick it becomes.

`KotakQuoteSource.fetch` names the instrument as `segment|token` in Kotak's segment vocabulary, `nse_cm|2885` for an NSE stock, and asks the quote endpoint on the host Kotak assigned the session at login, which the API client's `url` method supplies. Every value arrives as a string. Kotak's `ohlc.close` is not the previous close, so the source rebuilds the close as the last price less Kotak's `change`, which is what Kotak's market feed reports as the close.

Unlike the other quote sources, Kotak's sends its request with the `requests` library directly rather than through the API client, because the client drops the timeout. To keep the program offline it therefore replaces the `requests` name inside the Kotak quote module with a stand-in class that records each request and answers with a recorded-looking body. The API client is a stand-in too, holding a made-up consumer key, session and host. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice the request headers, which send the consumer key as `Authorization`; the close, which is 1381.2 less the change of 7.1 rather than Kotak's own close of 1381.2, and prints with the usual floating point tail; and the times, which are left empty because Kotak's `lstup_time` is a date that disagrees with the feed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/kotak/KotakQuoteSource/example_1_reliance_equity_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes import kotak as kotak_quotes
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
            payload (list): The decoded JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        """The decoded JSON body.

        Returns:
            list: The body.
        """
        return self._payload


class RecordedKotakServer:
    """A stand-in for the `requests` module that answers Kotak's quote endpoint with one recorded quote.

    Attributes:
        requests (list): The (url, header names) pairs of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, headers=None, timeout=None):
        """Answers a quote request with Kotak's quote for RELIANCE.

        Args:
            url (str): The quote URL, ending in the neosymbol.
            headers (dict): The request headers.
            timeout (float): How long the caller would wait.

        Returns:
            RecordedKotakResponse: The recorded answer.
        """
        self.requests.append((url, sorted(headers)))
        return RecordedKotakResponse(200, [
            {
                'exchange_token': '2885',
                'display_symbol': 'RELIANCE-EQ',
                'exchange': 'nse_cm',
                'lstup_time': 'Tue Sep 15 2026 05:30:00 GMT+0530',
                'ltp': '1381.2000',
                'last_traded_quantity': '14',
                'total_buy': '412776',
                'total_sell': '598340',
                'last_volume': '2183977',
                'change': '7.1000',
                'per_change': '0.52',
                'avg_cost': '1379.64',
                'open_int': '0',
                'ohlc': {
                    'open': '1375.0000',
                    'high': '1384.9000',
                    'low': '1372.5000',
                    'close': '1381.2000',
                },
                'depth': {
                    'buy': [
                        {
                            'price': '1381.1000',
                            'quantity': '311',
                            'orders': '6',
                        },
                    ],
                    'sell': [
                        {
                            'price': '1381.2000',
                            'quantity': '87',
                            'orders': '3',
                        },
                    ],
                },
            },
        ])


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


class RelianceEquityQuoteExample:
    """Fetches one NSE stock's Kotak quote and prints the request and the tick.

    Attributes:
        source (KotakQuoteSource): The quote source being shown.
        client (StandInKotakClient): The stand-in API client.
        server (RecordedKotakServer): The stand-in for the `requests` module.
    """

    def __init__(self):
        """Builds the source and its stand-ins, and points the Kotak quote module at the stand-in server.

        Returns:
            None: This method returns nothing.
        """
        self.source = KotakQuoteSource()
        self.client = StandInKotakClient()
        self.server = RecordedKotakServer()
        kotak_quotes.requests = self.server

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE-EQ',
            'lot_size': '1',
            'tick_size': '0.1',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000002',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Requests sent: {self.server.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    RelianceEquityQuoteExample().run()
