"""Asks Shoonya for the Nifty 50 index on a Sunday and for an NCDEX cotton contract, and shows what each answer becomes.

After the exchanges reset for the weekend, Noren can answer `GetQuotes` with nothing but a last price `lp` and a close `c`. That is still a usable quote: the tick simply has those two values and nothing else, in `quote` mode because it carries no order book.

Shoonya's NCDEX contracts cannot be quoted at all. Its NCDEX scrip file carries the trading symbol where the token belongs, so the stored token is `COTTON20NOV2026`, and `GetQuotes` answers it with a refusal inside a successful HTTP response. The refusal is not about the session, so `fetch` raises `QuoteUnavailable` rather than `NorenRefusal`, and the quote service moves on to the next broker.

Shoonya's API client is replaced by a stand-in class that answers each token with a recorded-looking body. Nothing leaves the process. The instant stamped on the tick is fixed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/shoonya/ShoonyaQuoteSource/example_2_index_after_hours_and_ncdex.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.shoonya import (
    ShoonyaQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class WeekendShoonyaClient:
    """A stand-in for Shoonya's API client answering `GetQuotes` the way it does on a Sunday.

    Attributes:
        requests (list): The body of every request received.
        answers (dict): Noren's body for each token.
    """

    def __init__(self):
        """Builds the stand-in with one answer for the index and one for the cotton contract.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []
        self.answers = {
            '26000': {
                'stat': 'Ok',
                'exch': 'NSE',
                'tsym': 'Nifty 50',
                'token': '26000',
                'lp': '25114.05',
                'c': '25114.05',
            },
            'COTTON20NOV2026': {
                'stat': 'Not_Ok',
                'emsg': 'Error Occurred : 5 "no data"',
            },
        }

    def post(self, url, data=None, timeout=None):
        """Answers a `GetQuotes` request with the body recorded for its token.

        Args:
            url (str): The endpoint asked.
            data (dict): The request body, naming the Noren exchange and token.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Noren's body under `data`.
        """
        self.requests.append(data)
        return {
            'status': 'success',
            'code': 200,
            'data': self.answers[data['token']],
        }


class IndexAfterHoursAndNcdexExample:
    """Asks Shoonya for an index on a Sunday and for an NCDEX contract.

    Attributes:
        source (ShoonyaQuoteSource): The quote source being shown.
        client (WeekendShoonyaClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = ShoonyaQuoteSource()
        self.client = WeekendShoonyaClient()

    def run(self):
        """Prints the index tick and what the cotton contract raises.

        Returns:
            None: This method returns nothing.
        """
        received_at = datetime.datetime(2026, 9, 20, 11, 0, 0, tzinfo=INDIA).timestamp()
        index_handle = {
            'broker_token': '26000',
            'order_symbol': 'Nifty 50',
            'lot_size': '1',
            'tick_size': '0.05',
        }
        index_identity = {
            'instrument_id': '66666666-6666-5666-8666-000000000001',
            'exchange': 'nse',
            'segment': 'nse_equity_indices',
            'shape': 'security',
        }
        tick = self.source.fetch(self.client, index_handle, index_identity, received_at)
        print(json.dumps(tick, indent=4))
        cotton_handle = {
            'broker_token': 'COTTON20NOV2026',
            'order_symbol': 'COTTON20NOV2026',
            'lot_size': '25',
            'tick_size': '10',
        }
        cotton_identity = {
            'instrument_id': '77777777-7777-5777-8777-000000000001',
            'exchange': 'ncdex',
            'segment': 'ncdex_commodity_futures',
            'shape': 'future',
        }
        try:
            self.source.fetch(self.client, cotton_handle, cotton_identity, received_at)
        except QuoteUnavailable as error:
            print(f'QuoteUnavailable: {error}')
            print(f'    log in again: {self.source.is_authentication_error(error)}')
        print(f'Requests sent: {self.client.requests}')


if __name__ == '__main__':
    IndexAfterHoursAndNcdexExample().run()
