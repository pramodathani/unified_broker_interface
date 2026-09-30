"""Shows a Noren platform downloader asking its two endpoints, `TPSeries` for intraday bars and `EODChartData` for daily ones, and reading both answers.

`NorenCandles` holds everything Flattrade and Shoonya share, and a real broker supplies only its name, host, rate, earliest date and the API class it logs in with. The program writes such a subclass for a made-up deployment at `noren.example.com`, so what is shown is the platform's behaviour rather than either broker's. Its constructor would open a PostgreSQL connection and log in, so the object is built without running it, as `test_runs/candle_parse.py` does, and the stand-in API is the one its `_build_api` returns.

The stored identifier `NSE|2885|RELIANCE-EQ` carries all three things the two endpoints need: `TPSeries` takes the exchange and numeric token with the window as epoch seconds, and `EODChartData` takes `NSE:RELIANCE-EQ`. The stand-in API records each POST and answers with bars shaped like the ones both hosts returned on 2026-09-11. Notice that the intraday answer arrives newest first and is sorted oldest first, that each bar's volume is its own `intv` rather than the day's running total `v` (188567 and 7938419 rather than 8776602), and that the daily bar arrives as a JSON encoded string and lands on midnight India time.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/noren/NorenCandles/example_1_intraday_and_daily_endpoints.py
"""

import datetime
import json

from stock_brokers.instruments.historical.noren import (
    NorenCandles,
)


class RecordedNorenAPI:
    """A stand-in for a Noren broker's API class that answers each endpoint with recorded bars.

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
            dict: The response envelope, with the decoded body under `data`.
        """
        self.requests.append((url, data))
        if url.endswith('/TPSeries'):
            body = [
                {
                    'stat': 'Ok',
                    'time': '11-09-2026 15:29:00',
                    'ssboe': '1789120740',
                    'into': '1257.50',
                    'inth': '1257.50',
                    'intl': '1257.50',
                    'intc': '1257.50',
                    'intv': '7938419',
                    'v': '8776602',
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
            ]
        else:
            bar = {
                'time': '11-SEP-2026',
                'into': '1267.00',
                'inth': '1267.40',
                'intl': '1253.00',
                'intc': '1257.50',
                'ssboe': '1789084800',
                'intv': '8777736.00',
            }
            body = [
                json.dumps(bar),
            ]
        return {
            'status_code': 200,
            'data': body,
        }


class ExampleDeploymentCandles(NorenCandles):
    """Downloads candles from a made-up Noren deployment, to show what a broker subclass supplies."""

    BROKER_NAME = 'example_noren'
    BASE_URL = 'https://noren.example.com/NorenWClientAPI'
    REQUESTS_PER_SECOND = 2.0
    EARLIEST_AVAILABLE_DATE = datetime.date(2020, 1, 1)

    def _build_api(self):
        """Builds the stand-in API in place of a logged-in broker API class.

        Returns:
            RecordedNorenAPI: A new stand-in.
        """
        return RecordedNorenAPI()


class IntradayAndDailyEndpointsExample:
    """Fetches and parses one intraday and one daily window.

    Attributes:
        api (RecordedNorenAPI): The stand-in API the downloader was given.
        candles (ExampleDeploymentCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader without opening a database connection and gives it its API.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(ExampleDeploymentCandles)
        self.api = self.candles._build_api()
        self.candles._api = self.api

    def fetch_and_print(self, interval):
        """Fetches 2026-09-11 for RELIANCE at one interval and prints the request and the bars.

        Args:
            interval (str): The stored interval name.

        Returns:
            None: This method returns nothing.
        """
        day = datetime.date(2026, 9, 11)
        payload = self.candles.fetch_candles('NSE|2885|RELIANCE-EQ', interval, day, day)
        url, body = self.api.requests[-1]
        print(f'{interval}: {url}')
        print(f'  body: {body}')
        for bar in self.candles.parse_response(payload, interval):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            india_time = bar_time.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
            print(f'  {india_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')

    def run(self):
        """Fetches the intraday window and then the daily one.

        Returns:
            None: This method returns nothing.
        """
        self.fetch_and_print('1minute')
        self.fetch_and_print('day')


if __name__ == '__main__':
    IntradayAndDailyEndpointsExample().run()
