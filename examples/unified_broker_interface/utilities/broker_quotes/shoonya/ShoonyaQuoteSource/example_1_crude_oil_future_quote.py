"""Fetches Shoonya's quote for an MCX crude oil future and shows the contract tick it becomes.

Shoonya is Finvasia's deployment of the Noren platform, so `ShoonyaQuoteSource` only names the broker and its `GetQuotes` endpoint, and `NorenQuoteSource` does the rest. Every mapped MCX contract sits under Noren's `MCX` exchange, which is what the request names. On MCX the quantities Noren sends are lots, as on its market feed, so nothing is converted here; the tick normalizer multiplies by the lot size later, exactly as it does for a streamed tick.

Shoonya's API client is replaced by a stand-in class that records the request and answers with a recorded-looking `GetQuotes` body for CRUDEOIL SEP in the envelope the real client returns. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice the Noren spelling of the token, `MCX|467013`; the open interest of 17552 lots; and the `change`, which is worked out from the last price and the close because this answer carries no `pc` field.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/shoonya/ShoonyaQuoteSource/example_1_crude_oil_future_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.shoonya import (
    ShoonyaQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedShoonyaClient:
    """A stand-in for Shoonya's API client that answers `GetQuotes` with one recorded quote.

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
        """Answers a `GetQuotes` request with Shoonya's quote for CRUDEOIL SEP.

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
                'exch': 'MCX',
                'tsym': 'CRUDEOIL18SEP26',
                'token': '467013',
                'ls': '100',
                'lp': '5725.00',
                'c': '5722.00',
                'o': '5702.00',
                'h': '5741.00',
                'l': '5698.00',
                'ap': '5719.42',
                'v': '70691',
                'ltq': '1',
                'ltt': '10:00:02',
                'ltd': '15-09-2026',
                'lut': '1789446603',
                'tbq': '1843',
                'tsq': '2011',
                'oi': '17552',
                'bp1': '5724.00',
                'bq1': '12',
                'bo1': '7',
                'sp1': '5725.00',
                'sq1': '9',
                'so1': '5',
            },
        }


class CrudeOilFutureQuoteExample:
    """Fetches one MCX future's Shoonya quote and prints the request and the tick.

    Attributes:
        source (ShoonyaQuoteSource): The quote source being shown.
        client (RecordedShoonyaClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = ShoonyaQuoteSource()
        self.client = RecordedShoonyaClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '467013',
            'order_symbol': 'CRUDEOIL18SEP26',
            'lot_size': '100',
            'tick_size': '1',
        }
        identity = {
            'instrument_id': '33333333-3333-5333-8333-000000000001',
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Broker: {self.source.BROKER_NAME}')
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    CrudeOilFutureQuoteExample().run()
