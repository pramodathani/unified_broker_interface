"""Fetches two windows of RELIANCE day bars from Fyers, one with bars and one Fyers reports as `no_data`.

Fyers is addressed by ticker, so the request carries `NSE:RELIANCE-EQ` together with a resolution code (`1D` for the stored `day`), and it always asks for open interest and continuous data. Fyers stamps a day bar at midnight UTC where Kite stamps midnight India time, which is the same trading day five and a half hours apart. `parse_response` moves every day bar onto midnight India time, so the bar stamped 2026-08-03 00:00 UTC is stored as 2026-08-03 00:00 India time. An empty window comes back as HTTP 200 with `s` holding `no_data`, and is read as no bars rather than an error.

A `FyersCandles` constructor opens a PostgreSQL connection and logs in to Fyers when the stored session has expired, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `FyersAPI`. The stand-in records each request and answers with a body shaped like Fyers' recorded answers, wrapped in the `status_code` and `data` envelope the real API class returns.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/fyers/FyersCandles/example_1_day_bars_stamped_in_utc.py
"""

import datetime

from stock_brokers.instruments.historical.fyers import (
    FyersCandles,
)


class RecordedFyersAPI:
    """A stand-in for `FyersAPI` that answers a window in 2026 with two day bars and any older window with `no_data`.

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
            dict: The response envelope, with Fyers' body under `data`.
        """
        self.requests.append((url, params))
        if params['range_from'] < '2000-01-01':
            body = {
                's': 'no_data',
                'candles': [],
            }
        else:
            body = {
                's': 'ok',
                'candles': [
                    [
                        1785715200,
                        1391.0,
                        1399.9,
                        1386.2,
                        1394.4,
                        6412337,
                    ],
                    [
                        1785801600,
                        1394.4,
                        1402.0,
                        1388.0,
                        1398.1,
                        5530124,
                    ],
                ],
            }
        return {
            'status_code': 200,
            'data': body,
        }


class DayBarsStampedInUtcExample:
    """Fetches and parses a window with bars and a window with none.

    Attributes:
        api (RecordedFyersAPI): The stand-in Fyers API.
        candles (FyersCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedFyersAPI()
        self.candles = object.__new__(FyersCandles)
        self.candles._api = self.api

    def fetch_and_print(self, start_date, end_date):
        """Fetches one window of RELIANCE day bars and prints the request and the bars.

        Args:
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            None: This method returns nothing.
        """
        payload = self.candles.fetch_candles('NSE:RELIANCE-EQ', 'day', start_date, end_date)
        url, parameters = self.api.requests[-1]
        print(f'Requested {url}')
        print(f'  parameters: {parameters}')
        print(f'  status: {payload["s"]}')
        bars = self.candles.parse_response(payload, 'day')
        print(f'  bars: {len(bars)}')
        for index, bar in enumerate(bars):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            sent_epoch = payload['candles'][index][0]
            sent_time = datetime.datetime.fromtimestamp(sent_epoch, datetime.timezone.utc)
            print(f'  sent {sent_time.isoformat()}, stored {bar_time.isoformat()}: open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')

    def run(self):
        """Fetches the window with bars, then the empty one.

        Returns:
            None: This method returns nothing.
        """
        self.fetch_and_print(datetime.date(2026, 8, 1), datetime.date(2026, 8, 4))
        self.fetch_and_print(datetime.date(1995, 1, 1), datetime.date(1995, 12, 31))


if __name__ == '__main__':
    DayBarsStampedInUtcExample().run()
