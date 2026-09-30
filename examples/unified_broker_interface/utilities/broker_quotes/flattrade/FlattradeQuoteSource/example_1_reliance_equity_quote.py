"""Fetches Flattrade's quote for RELIANCE on NSE and shows the contract tick it becomes.

Flattrade runs on the Noren platform, so `FlattradeQuoteSource` only names the broker and its `GetQuotes` endpoint; the request and the tick are built by `NorenQuoteSource`. The request names the instrument by its Noren exchange, `NSE` for a stock, and its bare token. Noren answers with every value as a string, under the same short names its market feed uses (`lp`, `c`, `o`, `h`, `l`, `v`, and five levels of `bp1`, `bq1`, `bo1` and so on), and the source turns those into numbers.

Flattrade's API client is replaced by a stand-in class that records the request and answers with a recorded-looking `GetQuotes` body for token 2885, in the envelope the real client returns. The real client would add the account's user id and session key to the body; the stand-in does not need them. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice the tick's `instrument_token`, `NSE|2885`, as Noren's feed spells it; the `change`, which is Noren's own percentage `pc`; `last_trade_time`, read from the `ltd` date and `ltt` time together; and `exchange_timestamp`, which is Noren's last update time `lut`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/flattrade/FlattradeQuoteSource/example_1_reliance_equity_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.flattrade import (
    FlattradeQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedFlattradeClient:
    """A stand-in for Flattrade's API client that answers `GetQuotes` with one recorded quote.

    Attributes:
        requests (list): The (url, body) pairs of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def post(self, url, data=None, timeout=None):
        """Answers a `GetQuotes` request with Flattrade's quote for RELIANCE.

        Args:
            url (str): The endpoint asked.
            data (dict): The request body, naming the Noren exchange and token.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Noren's body under `data`.
        """
        self.requests.append((url, data))
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'request_time': '10:00:04 15-09-2026',
                'stat': 'Ok',
                'exch': 'NSE',
                'tsym': 'RELIANCE-EQ',
                'token': '2885',
                'ls': '1',
                'ti': '0.10',
                'lp': '1381.20',
                'c': '1374.10',
                'o': '1375.00',
                'h': '1384.90',
                'l': '1372.50',
                'ap': '1379.64',
                'v': '2183977',
                'ltq': '14',
                'ltt': '10:00:02',
                'ltd': '15-09-2026',
                'lut': '1789446603',
                'tbq': '412776',
                'tsq': '598340',
                'pc': '0.52',
                'bp1': '1381.10',
                'bq1': '311',
                'bo1': '6',
                'bp2': '1381.00',
                'bq2': '1022',
                'bo2': '14',
                'sp1': '1381.20',
                'sq1': '87',
                'so1': '3',
                'sp2': '1381.30',
                'sq2': '640',
                'so2': '9',
            },
        }


class RelianceEquityQuoteExample:
    """Fetches one NSE stock's Flattrade quote and prints the request and the tick.

    Attributes:
        source (FlattradeQuoteSource): The quote source being shown.
        client (RecordedFlattradeClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FlattradeQuoteSource()
        self.client = RecordedFlattradeClient()

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
        print(f'Broker: {self.source.BROKER_NAME}')
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    RelianceEquityQuoteExample().run()
