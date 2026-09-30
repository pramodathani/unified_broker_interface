"""Fetches Fyers' depth quote for SBIN on NSE and shows the contract tick it becomes.

`FyersQuoteSource.fetch` asks Fyers' depth endpoint for one instrument by its Fyers symbol, such as `NSE:SBIN-EQ`, which is both the request parameter and the tick's `instrument_token`, because Fyers' market feed names instruments the same way. One depth answer carries everything the feed's full tick does: five levels of the order book with order counts, open, high, low, the previous close, the last price and quantity, the volume, the average price and the total bid and offer quantities.

Fyers' module is not yet in service, because its answer has not been checked against the live API; the body used here follows Fyers' published v3 example. The API client is replaced by a stand-in class that records the request and answers with that body in the envelope the real client returns. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice that `bids` and `ask` levels of `price`, `volume` and `ord` have become `price`, `quantity` and `orders`, and that the close is Fyers' `c`, because it agrees with the last price less the change `ch`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/fyers/FyersQuoteSource/example_1_sbin_depth_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.fyers import (
    FyersQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedFyersClient:
    """A stand-in for Fyers' API client that answers the depth endpoint with one recorded quote.

    Attributes:
        requests (list): The query parameters of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, params=None, timeout=None):
        """Answers a depth request with Fyers' quote for SBIN.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters, naming the symbol.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Fyers' body under `data`.
        """
        self.requests.append(params)
        return {
            'status': 'success',
            'code': 200,
            'data': {
                's': 'ok',
                'd': {
                    'NSE:SBIN-EQ': {
                        'totalbuyqty': 1204811,
                        'totalsellqty': 1739420,
                        'o': 812.0,
                        'h': 818.45,
                        'l': 809.1,
                        'c': 810.35,
                        'chp': 0.67,
                        'ch': 5.45,
                        'ltq': 25,
                        'ltt': 1789446602,
                        'ltp': 815.8,
                        'v': 6021844,
                        'atp': 814.22,
                        'lower_ckt': 729.35,
                        'upper_ckt': 891.35,
                        'expiry': '',
                        'oi': 0,
                        'oiflag': False,
                        'pdoi': 0,
                        'oipercent': 0,
                        'bids': [
                            {
                                'price': 815.75,
                                'volume': 412,
                                'ord': 9,
                            },
                            {
                                'price': 815.7,
                                'volume': 1880,
                                'ord': 21,
                            },
                        ],
                        'ask': [
                            {
                                'price': 815.8,
                                'volume': 95,
                                'ord': 2,
                            },
                            {
                                'price': 815.85,
                                'volume': 1310,
                                'ord': 17,
                            },
                        ],
                    },
                },
                'message': '',
            },
        }


class SbinDepthQuoteExample:
    """Fetches one NSE stock's Fyers quote and prints the request and the tick.

    Attributes:
        source (FyersQuoteSource): The quote source being shown.
        client (RecordedFyersClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FyersQuoteSource()
        self.client = RecordedFyersClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '10100000003045',
            'order_symbol': 'NSE:SBIN-EQ',
            'lot_size': '1',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000012',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    SbinDepthQuoteExample().run()
