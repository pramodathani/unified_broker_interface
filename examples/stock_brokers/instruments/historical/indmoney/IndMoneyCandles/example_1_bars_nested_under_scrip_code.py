"""Fetches one window of RELIANCE five minute bars from IND Money, where the answer nests each instrument's bars under its scrip code.

IND Money's chart endpoint takes the interval in its path and the window as epoch milliseconds at midnight India time, the end being midnight after the last day so the whole day is inside. Its answer maps each scrip code asked about to that instrument's bars, and `fetch_candles` hands `parse_response` only the part for the code it asked about. A scrip with nothing in the window may be present holding null or missing altogether, and both are read as an empty window. IND Money serves no open interest, so that column is always None. Intraday bar times are stored as the UTC instants the epochs decode to, and the program prints them in India time so they can be read against the 09:15 open.

An `IndMoneyCandles` constructor opens a PostgreSQL connection and logs in to IND Money when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `INDMoneyAPI`. The stand-in records each request and answers with bars shaped like IND Money's recorded answer, wrapped in the `status_code` and `data` envelope the real API class returns; for any scrip other than RELIANCE it answers with the code holding null.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/indmoney/IndMoneyCandles/example_1_bars_nested_under_scrip_code.py
"""

import datetime

from stock_brokers.instruments.historical.indmoney import (
    IndMoneyCandles,
)


class RecordedIndMoneyAPI:
    """A stand-in for `INDMoneyAPI` that answers with two recorded bars for RELIANCE and null for any other scrip.

    Attributes:
        requests (list): The (url, parameters) pairs it was asked for.
    """

    def __init__(self):
        """Builds the stand-in with no requests recorded.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, params=None):
        """Records a GET request and answers it.

        Args:
            url (str): The URL the downloader asked for.
            params (dict): The query parameters it sent.

        Returns:
            dict: The response envelope, with the map of scrip code to bars under `data`.
        """
        self.requests.append((url, params))
        scrip_code = params['scrip-codes']
        if scrip_code != 'NSE_2885':
            return {
                'status_code': 200,
                'data': {
                    scrip_code: None,
                },
            }
        return {
            'status_code': 200,
            'data': {
                'NSE_2885': {
                    'candles': [
                        {
                            'ts': 1788839100,
                            'o': 1306.8,
                            'h': 1306.8,
                            'l': 1300.0,
                            'c': 1303.1,
                            'v': 174555,
                        },
                        {
                            'ts': 1788839400,
                            'o': 1303.1,
                            'h': 1304.0,
                            'l': 1301.0,
                            'c': 1302.0,
                            'v': 98434,
                        },
                    ],
                },
            },
        }


class BarsNestedUnderScripCodeExample:
    """Fetches and parses a window for a scrip with bars and one without.

    Attributes:
        api (RecordedIndMoneyAPI): The stand-in IND Money API.
        candles (IndMoneyCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedIndMoneyAPI()
        self.candles = object.__new__(IndMoneyCandles)
        self.candles._api = self.api

    def fetch_and_print(self, scrip_code):
        """Fetches one day of five minute bars for a scrip and prints the request and the bars.

        Args:
            scrip_code (str): The scrip code, such as `NSE_2885`.

        Returns:
            None: This method returns nothing.
        """
        day = datetime.date(2026, 9, 8)
        payload = self.candles.fetch_candles(scrip_code, '5minute', day, day)
        url, parameters = self.api.requests[-1]
        print(f'Requested {url}')
        print(f'  parameters: {parameters}')
        bars = self.candles.parse_response(payload, '5minute')
        print(f'  bars: {len(bars)}')
        for bar in bars:
            bar_time, open_price, high, low, close, volume, open_interest = bar
            india_time = bar_time.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
            print(f'  {india_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')

    def run(self):
        """Fetches RELIANCE, then a scrip with nothing in the window.

        Returns:
            None: This method returns nothing.
        """
        self.fetch_and_print('NSE_2885')
        self.fetch_and_print('NFO_52175')


if __name__ == '__main__':
    BarsNestedUnderScripCodeExample().run()
