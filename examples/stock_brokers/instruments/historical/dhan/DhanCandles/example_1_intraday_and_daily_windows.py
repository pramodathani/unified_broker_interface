"""Fetches one intraday window and one daily window of RELIANCE bars from Dhan, and turns Dhan's columnar answer into bars.

Dhan serves intraday and daily candles from two endpoints that take the same body with differently formatted dates: the intraday one wants a time of day on each date and an interval code, the daily one wants bare dates. It answers with one array per field rather than one object per bar, and `parse_response` transposes them.

A `DhanCandles` constructor opens a PostgreSQL connection and logs in to Dhan when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `DhanAPI`. The stand-in records every POST and answers with arrays shaped like Dhan's recorded responses, wrapped in the `status_code` and `data` envelope the real API class returns. Notice that intraday bars keep the UTC offset their epoch decodes to, so 03:45 UTC is the 09:15 India time bar, while the daily bar, stamped with an epoch that decodes to 18:30 UTC, lands on midnight India time on 2002-01-01, and that a cash instrument's answer has no `open_interest` array, so open interest is None.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/dhan/DhanCandles/example_1_intraday_and_daily_windows.py
"""

import datetime

from stock_brokers.instruments.historical.dhan import (
    DhanCandles,
)


class RecordedDhanAPI:
    """A stand-in for `DhanAPI` that answers each endpoint with one recorded columnar response.

    Attributes:
        requests (list): The (url, body) pairs it was sent.
    """

    def __init__(self):
        """Builds the stand-in with no requests recorded.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def post(self, url, json=None):
        """Records a POST request and answers it with recorded arrays.

        Args:
            url (str): The endpoint the downloader called.
            json (dict): The request body it sent.

        Returns:
            dict: The response envelope, with the arrays under `data`.
        """
        self.requests.append((url, json))
        if url.endswith('/intraday'):
            data = {
                'timestamp': [
                    1788839100.0,
                    1788839400.0,
                ],
                'open': [
                    1306.8,
                    1303.1,
                ],
                'high': [
                    1306.8,
                    1304.0,
                ],
                'low': [
                    1300.0,
                    1301.0,
                ],
                'close': [
                    1303.1,
                    1302.0,
                ],
                'volume': [
                    174555.0,
                    98434.0,
                ],
            }
        else:
            data = {
                'timestamp': [
                    1009823400.0,
                ],
                'open': [
                    55.73,
                ],
                'high': [
                    56.46,
                ],
                'low': [
                    55.31,
                ],
                'close': [
                    55.75,
                ],
                'volume': [
                    688738.0,
                ],
            }
        return {
            'status_code': 200,
            'data': data,
        }


class IntradayAndDailyWindowsExample:
    """Fetches and parses one intraday and one daily window.

    Attributes:
        api (RecordedDhanAPI): The stand-in Dhan API.
        candles (DhanCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedDhanAPI()
        self.candles = object.__new__(DhanCandles)
        self.candles._api = self.api

    def fetch_and_print(self, interval, start_date, end_date):
        """Fetches one window of RELIANCE bars and prints the request and the bars.

        Args:
            interval (str): The stored interval name.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            None: This method returns nothing.
        """
        payload = self.candles.fetch_candles('2885|NSE_EQ|EQUITY', interval, start_date, end_date)
        url, body = self.api.requests[-1]
        print(f'{interval}: {url}')
        print(f'  body: {body}')
        for bar in self.candles.parse_response(payload, interval):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'  {bar_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')

    def run(self):
        """Fetches the intraday window and then the daily one.

        Returns:
            None: This method returns nothing.
        """
        self.fetch_and_print('5minute', datetime.date(2026, 9, 8), datetime.date(2026, 9, 8))
        self.fetch_and_print('day', datetime.date(2002, 1, 1), datetime.date(2002, 1, 31))


if __name__ == '__main__':
    IntradayAndDailyWindowsExample().run()
