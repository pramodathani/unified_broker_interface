"""Fetches a RELIANCE daily bar from Flattrade's `EODChartData` endpoint, then shows Flattrade refusing an expired session.

Daily bars come from a different Noren endpoint than intraday ones, addressed by `EXCHANGE:TRADINGSYMBOL` rather than by token, and each bar arrives as a JSON encoded string inside the answer list. `parse_response` decodes it and puts the bar at midnight India time on its trading date.

Noren refuses with HTTP 200 and an object carrying `stat` and `emsg`, so an expired session reaches `parse_response` rather than raising in the API class. There it becomes `CandleAuthenticationError`, which is what makes the base class log in once and try again. The stand-in for `FlattradeAPI` answers the first request with a recorded daily bar and the second with that refusal, each wrapped in the `status_code` and `data` envelope the real API class returns.

A `FlattradeCandles` constructor opens a PostgreSQL connection and logs in to Flattrade when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/flattrade/FlattradeCandles/example_2_daily_bar_and_expired_session.py
"""

import datetime
import json

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
)
from stock_brokers.instruments.historical.flattrade import (
    FlattradeCandles,
)


class ExpiringFlattradeAPI:
    """A stand-in for `FlattradeAPI` whose session expires after the first request.

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
        """Records a POST request and answers with a daily bar the first time and a refusal afterwards.

        Args:
            url (str): The endpoint the downloader called.
            data (dict): The request fields it sent.

        Returns:
            dict: The response envelope, with the decoded body under `data`.
        """
        self.requests.append((url, data))
        if len(self.requests) > 1:
            return {
                'status_code': 200,
                'data': {
                    'stat': 'Not_Ok',
                    'emsg': 'Session Expired :  Invalid Session Key',
                },
            }
        bar = {
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
                json.dumps(bar),
            ],
        }


class DailyBarAndExpiredSessionExample:
    """Fetches a daily bar, then a window the expired session refuses.

    Attributes:
        api (ExpiringFlattradeAPI): The stand-in Flattrade API.
        candles (FlattradeCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = ExpiringFlattradeAPI()
        self.candles = object.__new__(FlattradeCandles)
        self.candles._api = self.api

    def run(self):
        """Fetches two daily windows and prints what each gave.

        Returns:
            None: This method returns nothing.
        """
        start_date = datetime.date(2026, 9, 7)
        end_date = datetime.date(2026, 9, 11)
        payload = self.candles.fetch_candles('NSE|2885|RELIANCE-EQ', 'day', start_date, end_date)
        url, body = self.api.requests[0]
        print(f'Requested {url}')
        print(f'  body: {body}')
        print(f'  answer element: {payload[0]}')
        for bar in self.candles.parse_response(payload, 'day'):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'  {bar_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')
        payload = self.candles.fetch_candles('NSE|2885|RELIANCE-EQ', 'day', start_date, end_date)
        try:
            self.candles.parse_response(payload, 'day')
        except CandleAuthenticationError as error:
            print(f'Second window: {type(error).__name__}: {error}')


if __name__ == '__main__':
    DailyBarAndExpiredSessionExample().run()
