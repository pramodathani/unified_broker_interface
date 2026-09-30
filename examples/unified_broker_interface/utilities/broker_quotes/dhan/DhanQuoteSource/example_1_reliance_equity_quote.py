"""Fetches Dhan's quote for RELIANCE on NSE and shows the contract tick it becomes.

`DhanQuoteSource.fetch` works out Dhan's exchange segment from the instrument's identity (`NSE_EQ` for an NSE stock), asks Dhan's market feed quote endpoint for the security id under that segment, and copies the answer into a tick in the market feeds' contract shape. The request carries the session's `access-token` and the account's `client-id` as headers, which the source reads from the API client.

The Dhan API client is replaced by a stand-in class. It holds a made-up login and client id, records the request it receives, and answers with a recorded-looking quote for security id 2885 in the envelope the real client returns, which keeps Dhan's own body, `data.data`, underneath. Nothing leaves the process and no login happens. The instant stamped on the tick is fixed.

In the output, notice the tick's `instrument_token`, `1:2885`, which is Dhan's numeric segment code and the security id as Dhan's feed spells them; the `change` worked out from the last price and the close; and `last_trade_time`, which Dhan sends as `DD/MM/YYYY HH:MM:SS` India time text and the tick carries as epoch seconds.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/dhan/DhanQuoteSource/example_1_reliance_equity_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.dhan import (
    DhanQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedDhanClient:
    """A stand-in for Dhan's API client that answers the quote endpoint with one recorded quote.

    Attributes:
        requests (list): The body and header names of every request received.
    """

    def __init__(self):
        """Builds the stand-in with a made-up account and no requests received.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'client_id': '1100012345',
        }
        self.requests = []

    def _current_login(self):
        """The stored login, as the real client reads it before every request.

        Returns:
            dict: The login, holding a made-up access token.
        """
        return {
            'access_token': 'example-access-token',
        }

    def post(self, url, json=None, headers=None, timeout=None):
        """Answers a quote request with Dhan's quote for RELIANCE.

        Args:
            url (str): The endpoint asked.
            json (dict): The request body, naming security ids by segment.
            headers (dict): The request headers.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Dhan's body under `data`.
        """
        header_names = sorted(headers)
        self.requests.append((json, header_names))
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'status': 'success',
                'data': {
                    'NSE_EQ': {
                        '2885': {
                            'average_price': 1379.64,
                            'buy_quantity': 412776,
                            'sell_quantity': 598340,
                            'last_price': 1381.2,
                            'last_quantity': 14,
                            'last_trade_time': '15/09/2026 10:00:02',
                            'lower_circuit_limit': 1243.1,
                            'upper_circuit_limit': 1519.3,
                            'net_change': 7.1,
                            'volume': 2183977,
                            'oi': 0,
                            'oi_day_high': 0,
                            'oi_day_low': 0,
                            'ohlc': {
                                'open': 1375.0,
                                'close': 1374.1,
                                'high': 1384.9,
                                'low': 1372.5,
                            },
                            'depth': {
                                'buy': [
                                    {
                                        'quantity': 311,
                                        'orders': 6,
                                        'price': 1381.1,
                                    },
                                    {
                                        'quantity': 1022,
                                        'orders': 14,
                                        'price': 1381.0,
                                    },
                                ],
                                'sell': [
                                    {
                                        'quantity': 87,
                                        'orders': 3,
                                        'price': 1381.2,
                                    },
                                    {
                                        'quantity': 640,
                                        'orders': 9,
                                        'price': 1381.3,
                                    },
                                ],
                            },
                        },
                    },
                },
            },
        }


class RelianceEquityQuoteExample:
    """Fetches one NSE stock's Dhan quote and prints the request and the tick.

    Attributes:
        source (DhanQuoteSource): The quote source being shown.
        client (RecordedDhanClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = DhanQuoteSource()
        self.client = RecordedDhanClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE',
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
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    RelianceEquityQuoteExample().run()
