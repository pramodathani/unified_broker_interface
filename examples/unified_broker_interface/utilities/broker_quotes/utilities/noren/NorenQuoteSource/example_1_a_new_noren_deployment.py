"""Adds quotes for a new broker on the Noren platform by subclassing `NorenQuoteSource`, and fetches a NIFTY future with it.

`NorenQuoteSource` holds everything Noren brokers share: working out the Noren exchange from the instrument's identity, the `GetQuotes` request, reading the string fields of the answer, and recognising a refused session. A Noren broker's module therefore only sets `BROKER_NAME` and `QUOTE_URL`, as Flattrade's and Shoonya's do. This program does the same for an imaginary Noren deployment called `example_noren`.

The instrument is a NIFTY index future, which sits under Noren's `NFO` exchange. The API client is a stand-in class that records the request and answers with a recorded-looking `GetQuotes` body in the envelope a real client returns. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice that the request went to the subclass's own URL, that the token is spelled `NFO|35001`, that the answer's `ltt` already carries a date and so is read on its own, and that `change` is worked out from the last price and the close because the answer has no `pc` field.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/noren/NorenQuoteSource/example_1_a_new_noren_deployment.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.utilities.noren import (
    NorenQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class ExampleNorenQuoteSource(NorenQuoteSource):
    """Fetches quotes from an imaginary Noren deployment."""

    BROKER_NAME = 'example_noren'
    QUOTE_URL = 'https://noren.example/NorenWClientAPI/GetQuotes'


class RecordedNorenClient:
    """A stand-in for a Noren broker's API client that answers `GetQuotes` with one recorded quote.

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
        """Answers a `GetQuotes` request with a quote for NIFTY OCT futures.

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
                'stat': 'Ok',
                'exch': 'NFO',
                'tsym': 'NIFTY27OCT26F',
                'token': '35001',
                'lp': '25150.50',
                'c': '25100.00',
                'o': '25110.00',
                'h': '25188.00',
                'l': '25090.20',
                'ap': '25141.37',
                'v': '1873500',
                'ltq': '75',
                'ltt': '15-09-2026 10:00:01',
                'lut': '1789446603',
                'tbq': '262500',
                'tsq': '301875',
                'oi': '12345000',
                'bp1': '25150.00',
                'bq1': '75',
                'bo1': '3',
                'sp1': '25151.00',
                'sq1': '150',
                'so1': '4',
            },
        }


class NewNorenDeploymentExample:
    """Fetches one NIFTY future's quote from the imaginary Noren deployment and prints the tick.

    Attributes:
        source (ExampleNorenQuoteSource): The quote source being shown.
        client (RecordedNorenClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = ExampleNorenQuoteSource()
        self.client = RecordedNorenClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '35001',
            'order_symbol': 'NIFTY27OCT26F',
            'lot_size': '75',
            'tick_size': '0.1',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000003',
            'exchange': 'nse',
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    NewNorenDeploymentExample().run()
