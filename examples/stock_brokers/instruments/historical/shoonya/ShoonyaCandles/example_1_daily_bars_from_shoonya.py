"""Fetches a week of RELIANCE daily bars from Shoonya's `EODChartData` endpoint and reads them.

Shoonya runs the Noren platform, so `ShoonyaCandles` adds only what is particular to it to `NorenCandles`: its host, its rate of one request a second (a tenth of Flattrade's) and a daily history that is a rolling five years. The program prints those settings and fetches one daily window, which goes to Shoonya's host addressed by `NSE:RELIANCE-EQ` with the window as epoch seconds at midnight India time.

A `ShoonyaCandles` constructor opens a PostgreSQL connection and logs in to Shoonya when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `ShoonyaAPI`. The stand-in records the POST and answers with two daily bars, each a JSON encoded string as Noren sends them, wrapped in the `status_code` and `data` envelope the real API class returns. Notice that the bars, sent newest first, come back oldest first, and that every bar lands on midnight India time on its trading date and has no open interest.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/shoonya/ShoonyaCandles/example_1_daily_bars_from_shoonya.py
"""

import datetime
import json

from stock_brokers.instruments.historical.shoonya import (
    ShoonyaCandles,
)


class RecordedShoonyaAPI:
    """A stand-in for `ShoonyaAPI` that answers `EODChartData` with two recorded daily bars.

    Attributes:
        requests (list): The (url, body) pairs it was sent.
    """

    def __init__(self):
        """Builds the stand-in with no requests recorded.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def post(self, url, data=None):
        """Records a POST request and answers it with two daily bars.

        Args:
            url (str): The endpoint the downloader called.
            data (dict): The request fields it sent.

        Returns:
            dict: The response envelope, with the bars under `data`.
        """
        self.requests.append((url, data))
        thursday = {
            'time': '10-SEP-2026',
            'into': '1271.20',
            'inth': '1276.00',
            'intl': '1264.10',
            'intc': '1267.00',
            'ssboe': '1788998400',
            'intv': '6120455.00',
        }
        friday = {
            'time': '11-SEP-2026',
            'into': '1267.00',
            'inth': '1267.40',
            'intl': '1253.00',
            'intc': '1257.50',
            'ssboe': '1789084800',
            'intv': '8777736.00',
        }
        return {
            'status_code': 200,
            'data': [
                json.dumps(friday),
                json.dumps(thursday),
            ],
        }


class DailyBarsFromShoonyaExample:
    """Prints Shoonya's settings, then fetches and parses one daily window.

    Attributes:
        api (RecordedShoonyaAPI): The stand-in Shoonya API.
        candles (ShoonyaCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedShoonyaAPI()
        self.candles = object.__new__(ShoonyaCandles)
        self.candles._api = self.api

    def run(self):
        """Prints the settings, fetches the week to 2026-09-11 and prints the bars.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {ShoonyaCandles.BROKER_NAME}')
        print(f'Host: {ShoonyaCandles.BASE_URL}')
        print(f'Requests a second: {ShoonyaCandles.REQUESTS_PER_SECOND}')
        print(f'Earliest date: {ShoonyaCandles.EARLIEST_AVAILABLE_DATE}')
        payload = self.candles.fetch_candles(
            'NSE|2885|RELIANCE-EQ',
            'day',
            datetime.date(2026, 9, 7),
            datetime.date(2026, 9, 11),
        )
        url, body = self.api.requests[0]
        print(f'Requested {url}')
        print(f'  body: {body}')
        for bar in self.candles.parse_response(payload, 'day'):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'  {bar_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')


if __name__ == '__main__':
    DailyBarsFromShoonyaExample().run()
