"""Fetches one day of RELIANCE one minute bars from Flattrade's `TPSeries` endpoint and reads them.

Flattrade runs the Noren platform, so `FlattradeCandles` adds only what is particular to it to `NorenCandles`: its host, its documented ten requests a second, and a daily history that reaches back to 2019. The program prints those settings and then fetches one window, so the request can be seen going to Flattrade's host with the exchange, the numeric token and the window as epoch seconds.

A `FlattradeCandles` constructor opens a PostgreSQL connection and logs in to Flattrade when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `FlattradeAPI`. The stand-in records the POST and answers with two bars shaped like the ones Flattrade returned for 2026-09-11, newest first as Noren sends them, wrapped in the `status_code` and `data` envelope the real API class returns. Notice that the bars come back oldest first, printed here in India time.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/flattrade/FlattradeCandles/example_1_one_minute_bars_from_flattrade.py
"""

import datetime

from stock_brokers.instruments.historical.flattrade import (
    FlattradeCandles,
)


class RecordedFlattradeAPI:
    """A stand-in for `FlattradeAPI` that answers `TPSeries` with two recorded bars.

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
        """Records a POST request and answers it with recorded bars.

        Args:
            url (str): The endpoint the downloader called.
            data (dict): The request fields it sent.

        Returns:
            dict: The response envelope, with the bars under `data`.
        """
        self.requests.append((url, data))
        return {
            'status_code': 200,
            'data': [
                {
                    'stat': 'Ok',
                    'time': '11-09-2026 09:16:00',
                    'ssboe': '1789098360',
                    'into': '1262.70',
                    'inth': '1263.90',
                    'intl': '1262.10',
                    'intc': '1263.40',
                    'intv': '64210',
                    'v': '252777',
                    'oi': '0',
                },
                {
                    'stat': 'Ok',
                    'time': '11-09-2026 09:15:00',
                    'ssboe': '1789098300',
                    'into': '1266.40',
                    'inth': '1267.40',
                    'intl': '1261.50',
                    'intc': '1262.70',
                    'intv': '188567',
                    'v': '188567',
                    'oi': '0',
                },
            ],
        }


class OneMinuteBarsFromFlattradeExample:
    """Prints Flattrade's settings, then fetches and parses one window.

    Attributes:
        api (RecordedFlattradeAPI): The stand-in Flattrade API.
        candles (FlattradeCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedFlattradeAPI()
        self.candles = object.__new__(FlattradeCandles)
        self.candles._api = self.api

    def run(self):
        """Prints the settings, fetches 2026-09-11 and prints the bars.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {FlattradeCandles.BROKER_NAME}')
        print(f'Host: {FlattradeCandles.BASE_URL}')
        print(f'Requests a second: {FlattradeCandles.REQUESTS_PER_SECOND}')
        print(f'Earliest date: {FlattradeCandles.EARLIEST_AVAILABLE_DATE}')
        day = datetime.date(2026, 9, 11)
        payload = self.candles.fetch_candles('NSE|2885|RELIANCE-EQ', '1minute', day, day)
        url, body = self.api.requests[0]
        print(f'Requested {url}')
        print(f'  body: {body}')
        india = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        for bar in self.candles.parse_response(payload, '1minute'):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'  {bar_time.astimezone(india).isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')


if __name__ == '__main__':
    OneMinuteBarsFromFlattradeExample().run()
