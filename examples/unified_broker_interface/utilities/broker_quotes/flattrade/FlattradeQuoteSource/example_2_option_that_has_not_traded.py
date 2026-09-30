"""Fetches Flattrade's quote for a BSE option that has not traded today, and shows how the thin answer becomes a tick.

A far strike can go a whole session without a trade. Noren then answers `GetQuotes` with a last trade time of `00:00:00`, a last quantity of 0, no high or low, and here no order book either. `NorenQuoteSource` reads that midnight time as no time at all, rather than as a trade at midnight, and a quote without an order book becomes a tick in `quote` mode rather than `full` mode.

The instrument is a SENSEX option on BSE's derivatives exchange, so the request names Noren's `BFO` exchange. Flattrade's API client is replaced by a stand-in class that records the request and answers with a recorded-looking body. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice `"mode": "quote"`, the empty order book, `last_trade_time` of null, and the high and low that are null because Noren did not send them.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/flattrade/FlattradeQuoteSource/example_2_option_that_has_not_traded.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.flattrade import (
    FlattradeQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class UntradedOptionFlattradeClient:
    """A stand-in for Flattrade's API client that answers with a quote for an option that has not traded.

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
        """Answers a `GetQuotes` request with the untraded option's quote.

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
                'exch': 'BFO',
                'tsym': 'SENSEX2691877200CE',
                'token': '1133467',
                'lp': '12.40',
                'c': '12.40',
                'o': '0.00',
                'ltq': '0',
                'ltt': '00:00:00',
                'ltd': '15-09-2026',
                'lut': '1789446590',
                'v': '0',
                'oi': '1180',
            },
        }


class OptionThatHasNotTradedExample:
    """Fetches one untraded BSE option's Flattrade quote and prints the tick.

    Attributes:
        source (FlattradeQuoteSource): The quote source being shown.
        client (UntradedOptionFlattradeClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FlattradeQuoteSource()
        self.client = UntradedOptionFlattradeClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '1133467',
            'order_symbol': 'SENSEX2691877200CE',
            'lot_size': '20',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '55555555-5555-5555-8555-000000000001',
            'exchange': 'bse',
            'segment': 'bse_equity_index_options',
            'shape': 'option',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    OptionThatHasNotTradedExample().run()
