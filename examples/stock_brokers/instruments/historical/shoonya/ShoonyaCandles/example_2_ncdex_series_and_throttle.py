"""Reads a Shoonya NCDEX series identifier, fetches its minute bars, and shows Shoonya throttling a request.

Shoonya lists NCDEX, which Flattrade does not, and needs no code of its own for it: the exchange name `NCX` comes straight from Shoonya's scrip files, and `series_context` reads it as the `ncdex` exchange with derivative segments. The window is then asked of `TPSeries` with that exchange name.

Shoonya allows about one request a second, and a Noren throttle arrives as HTTP 200 carrying an object with `stat` of `Not_Ok` and a `Rate_Limited` message. `parse_response` raises that as `CandleThrottled`, which makes the base class back off and retry the same window rather than count it against the series. The stand-in for `ShoonyaAPI` records the POST and answers with that throttle, wrapped in the `status_code` and `data` envelope the real API class returns.

A `ShoonyaCandles` constructor opens a PostgreSQL connection and logs in to Shoonya when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/shoonya/ShoonyaCandles/example_2_ncdex_series_and_throttle.py
"""

import datetime

from stock_brokers.instruments.historical.base import (
    CandleThrottled,
)
from stock_brokers.instruments.historical.shoonya import (
    ShoonyaCandles,
)


class ThrottlingShoonyaAPI:
    """A stand-in for `ShoonyaAPI` that answers every request with Noren's rate limit refusal.

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
        """Records a POST request and refuses it for rate.

        Args:
            url (str): The endpoint the downloader called.
            data (dict): The request fields it sent.

        Returns:
            dict: The response envelope, with the refusal object under `data`.
        """
        self.requests.append((url, data))
        return {
            'status_code': 200,
            'data': {
                'stat': 'Not_Ok',
                'emsg': 'Rate_Limited: too many requests',
            },
        }


class NcdexSeriesAndThrottleExample:
    """Reads an NCDEX identifier and fetches a window the stand-in throttles.

    Attributes:
        api (ThrottlingShoonyaAPI): The stand-in Shoonya API.
        candles (ShoonyaCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = ThrottlingShoonyaAPI()
        self.candles = object.__new__(ShoonyaCandles)
        self.candles._api = self.api

    def run(self):
        """Reads the identifier, fetches one window and prints the throttle.

        Returns:
            None: This method returns nothing.
        """
        identifier = 'NCX|61452|GUARSEED10DEC26'
        context = ShoonyaCandles.series_context(identifier)
        print(f'{identifier}: token {context.broker_token}, exchange {context.exchange}, {len(context.segments)} derivative segments to search')
        day = datetime.date(2026, 9, 11)
        payload = self.candles.fetch_candles(identifier, '5minute', day, day)
        url, body = self.api.requests[0]
        print(f'Requested {url}')
        print(f'  body: {body}')
        try:
            self.candles.parse_response(payload, '5minute')
        except CandleThrottled as error:
            print(f'{type(error).__name__}: {error}')


if __name__ == '__main__':
    NcdexSeriesAndThrottleExample().run()
