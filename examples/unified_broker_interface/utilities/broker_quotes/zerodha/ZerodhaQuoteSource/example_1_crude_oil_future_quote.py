"""Fetches Zerodha's quote for an MCX crude oil future and shows the contract tick it becomes.

`ZerodhaQuoteSource.fetch` asks Kite's quote endpoint for one instrument by its instrument token and copies the answer into a tick in the market feeds' contract shape. Kite's quote uses the same field names as its market feed, so most values are copied as they are. The two times arrive as India time text and become epoch seconds, and the tick's `instrument_token` is the Kite token as an integer, exactly as Kite's feed spells it.

The Kite API client is replaced by a stand-in class that answers with a recorded-looking quote for CRUDEOIL SEP, token 111477767, in the envelope the real client returns after it has unwrapped Kite's `data`. So the program sends nothing over the network and needs no Zerodha login. The instant stamped on the tick is fixed.

In the output, notice that quantities stay in lots, as on the feed, that `ohlc.close` is the previous session's close, and that `last_trade_time` and `exchange_timestamp` are now epoch seconds.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/zerodha/ZerodhaQuoteSource/example_1_crude_oil_future_quote.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.zerodha import (
    ZerodhaQuoteSource,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RecordedKiteClient:
    """A stand-in for Zerodha's API client that answers the quote endpoint with one recorded quote.

    Attributes:
        requests (list): The (url, params) pairs of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, params=None, timeout=None):
        """Answers a quote request with Kite's quote for CRUDEOIL SEP.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters, whose `i` is the instrument token.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Kite's quotes keyed by instrument token under `data`.
        """
        self.requests.append((url, params))
        return {
            'status': 'success',
            'code': 200,
            'data': {
                '111477767': {
                    'instrument_token': 111477767,
                    'timestamp': '2026-09-15 10:00:03',
                    'last_trade_time': '2026-09-15 10:00:02',
                    'last_price': 5725.0,
                    'last_quantity': 1,
                    'buy_quantity': 1843,
                    'sell_quantity': 2011,
                    'volume': 70691,
                    'average_price': 5719.42,
                    'oi': 17552,
                    'oi_day_high': 17901,
                    'oi_day_low': 17410,
                    'net_change': 0,
                    'lower_circuit_limit': 5268.0,
                    'upper_circuit_limit': 6181.0,
                    'ohlc': {
                        'open': 5702.0,
                        'high': 5741.0,
                        'low': 5698.0,
                        'close': 5722.0,
                    },
                    'depth': {
                        'buy': [
                            {
                                'price': 5724.0,
                                'quantity': 12,
                                'orders': 7,
                            },
                            {
                                'price': 5723.0,
                                'quantity': 31,
                                'orders': 14,
                            },
                        ],
                        'sell': [
                            {
                                'price': 5725.0,
                                'quantity': 9,
                                'orders': 5,
                            },
                            {
                                'price': 5726.0,
                                'quantity': 22,
                                'orders': 11,
                            },
                        ],
                    },
                },
            },
        }


class CrudeOilFutureQuoteExample:
    """Fetches one MCX future's Zerodha quote and prints the tick.

    Attributes:
        source (ZerodhaQuoteSource): The quote source being shown.
        client (RecordedKiteClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = ZerodhaQuoteSource()
        self.client = RecordedKiteClient()

    def run(self):
        """Prints the request sent and the contract tick.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '111477767',
            'order_symbol': 'CRUDEOIL26SEPFUT',
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
        print(f'Requests sent: {self.client.requests}')
        print(json.dumps(tick, indent=4))


if __name__ == '__main__':
    CrudeOilFutureQuoteExample().run()
