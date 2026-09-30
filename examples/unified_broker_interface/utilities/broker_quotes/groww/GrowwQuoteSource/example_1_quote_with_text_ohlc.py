"""Fetches Groww's quote for an NSE stock and shows the contract tick it becomes, including Groww's `ohlc` sent as text.

`GrowwQuoteSource.fetch` asks Groww's live data endpoint for one instrument by exchange, Groww's own segment (`CASH` for a stock) and trading symbol. The tick's `instrument_token` is spelled `NSE|CASH|<exchange token>`, as Groww's market feed spells it. Groww's published example prints `ohlc` as a string, `"{open: 149.5,high: 150.5,low: 148.5,close: 149.5}"`, rather than as an object, and the source reads either form. The last trade time arrives in epoch milliseconds and becomes epoch seconds, and the order book levels carry no order counts.

Groww's module is not yet in service, because the account is not entitled to live data; the body used here follows Groww's published example. The API client is replaced by a stand-in class that records the request and answers with that body, already unwrapped from Groww's `payload`, in the envelope the real client returns. Nothing leaves the process. The instant stamped on the tick is fixed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/groww/GrowwQuoteSource/example_1_quote_with_text_ohlc.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.groww import (
    GrowwQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedGrowwClient:
    """A stand-in for Groww's API client that answers the live quote endpoint with one recorded quote.

    Attributes:
        requests (list): The query parameters of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, timeout=None, params=None):
        """Answers a live quote request with Groww's quote for NHPC.

        Args:
            url (str): The endpoint asked.
            timeout (float): How long the caller would wait.
            params (dict): The query parameters, naming the exchange, segment and trading symbol.

        Returns:
            dict: The client's envelope, holding Groww's payload under `data`.
        """
        self.requests.append(params)
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'average_price': 82.47,
                'bid_quantity': 5120,
                'bid_price': 82.5,
                'day_change': 0.6,
                'day_change_perc': 0.73,
                'upper_circuit_limit': 90.2,
                'lower_circuit_limit': 73.8,
                'ohlc': '{open: 82.1,high: 82.95,low: 81.85,close: 81.95}',
                'depth': {
                    'buy': [
                        {
                            'price': 82.5,
                            'quantity': 5120,
                        },
                        {
                            'price': 82.45,
                            'quantity': 18300,
                        },
                    ],
                    'sell': [
                        {
                            'price': 82.55,
                            'quantity': 9400,
                        },
                        {
                            'price': 82.6,
                            'quantity': 22710,
                        },
                    ],
                },
                'high_trade_range': None,
                'implied_volatility': None,
                'last_trade_quantity': 150,
                'last_trade_time': 1789446602000,
                'low_trade_range': None,
                'last_price': 82.55,
                'market_cap': None,
                'offer_price': 82.55,
                'offer_quantity': 9400,
                'oi_day_change': 0,
                'oi_day_change_percentage': 0,
                'open_interest': None,
                'previous_open_interest': None,
                'total_buy_quantity': 1843210,
                'total_sell_quantity': 2290440,
                'volume': 11872033,
                'week_52_high': 118.4,
                'week_52_low': 71.0,
            },
        }


class QuoteWithTextOhlcExample:
    """Fetches one NSE stock's Groww quote and prints the request and the tick.

    Attributes:
        source (GrowwQuoteSource): The quote source being shown.
        client (RecordedGrowwClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = GrowwQuoteSource()
        self.client = RecordedGrowwClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '17400',
            'order_symbol': 'NHPC',
            'lot_size': '1',
            'tick_size': '0.01',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000013',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        received_at = datetime.datetime(2026, 9, 15, 10, 0, 5, tzinfo=INDIA).timestamp()
        tick = self.source.fetch(self.client, handle, identity, received_at)
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    QuoteWithTextOhlcExample().run()
