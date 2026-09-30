"""Fetches INDmoney's quote for RELIANCE on NSE and shows the contract tick it becomes, including numbers sent with Indian digit grouping.

`IndmoneyQuoteSource.fetch` names the instrument to INDstocks by a scrip code, `NSE_2885` for an NSE stock, and the answer is keyed by the same code. The quote uses names of its own: `live_price`, `day_open`, `day_high`, `day_low`, `prev_close`, `volume` and `open_interest`. Its order book is five rows of buy and sell pairs whose numbers are strings with Indian digit grouping, such as `"1,56,975"`, and no order counts. The source removes the grouping, and the tick's `instrument_token` becomes `NSE:2885`, as INDmoney's market feed spells it.

INDmoney's API client is replaced by a stand-in class that records the request and answers with a recorded-looking body in the envelope the real client returns after unwrapping `data`. Nothing leaves the process. The instant stamped on the tick is fixed.

In the output, notice that `"1,56,975"` has become the number 156975, that every `orders` is null, and that `ohlc.close` is INDstocks' previous close, from which the `change` is worked out.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/indmoney/IndmoneyQuoteSource/example_1_reliance_with_grouped_digits.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.indmoney import (
    IndmoneyQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedIndmoneyClient:
    """A stand-in for INDmoney's API client that answers the full quote endpoint with one recorded quote.

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
        """Answers a full quote request with INDstocks' quote for RELIANCE.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters, naming the scrip code.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding the quotes keyed by scrip code under `data`.
        """
        self.requests.append(params)
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'NSE_2885': {
                    'live_price': 1381.2,
                    'day_open': 1375.0,
                    'day_high': 1384.9,
                    'day_low': 1372.5,
                    'prev_close': 1374.1,
                    'volume': 2183977,
                    'open_interest': 0,
                    'upper_circuit': 1511.5,
                    'lower_circuit': 1236.7,
                    'market_depth': {
                        'NSE_2885': {
                            'aggregate': {
                                'total_buy': '4,12,776',
                                'total_sell': '5,98,340',
                            },
                            'depth': [
                                {
                                    'buy': {
                                        'price': '1,381.10',
                                        'quantity': '311',
                                    },
                                    'sell': {
                                        'price': '1,381.20',
                                        'quantity': '87',
                                    },
                                },
                                {
                                    'buy': {
                                        'price': '1,381.00',
                                        'quantity': '1,56,975',
                                    },
                                    'sell': {
                                        'price': '1,381.30',
                                        'quantity': '640',
                                    },
                                },
                            ],
                        },
                    },
                },
            },
        }


class RelianceWithGroupedDigitsExample:
    """Fetches one NSE stock's INDmoney quote and prints the request and the tick.

    Attributes:
        source (IndmoneyQuoteSource): The quote source being shown.
        client (RecordedIndmoneyClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = IndmoneyQuoteSource()
        self.client = RecordedIndmoneyClient()

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
    RelianceWithGroupedDigitsExample().run()
