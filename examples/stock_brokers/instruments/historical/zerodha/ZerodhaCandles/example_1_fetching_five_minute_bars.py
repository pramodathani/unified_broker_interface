"""Fetches one window of five minute RELIANCE futures bars from Kite and reads them into stored bars.

A `ZerodhaCandles` downloader is normally built with no arguments, and its constructor then opens a PostgreSQL connection for the progress table and logs in to Kite if the stored session has expired. Neither is wanted here, so the program builds the object without running its constructor, exactly as the offline suite `test_runs/candle_parse.py` does, and gives it a stand-in for the `ZerodhaAPI` object it would otherwise hold. `fetch_candles` and `parse_response` need nothing else.

The stand-in records the URL and query parameters it is asked for and answers with a response shaped like the one Kite returned on 2026-09-11, wrapped in the `status_code` and `data` envelope the real API class returns. Notice three things in the output: the stored interval name `5minute` is sent to Kite as `5minute` while `1minute` would have been sent as `minute`, `oi=1` is always asked for, and the seventh element of each candle becomes the bar's open interest.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/zerodha/ZerodhaCandles/example_1_fetching_five_minute_bars.py
"""

import datetime

from stock_brokers.instruments.historical.zerodha import (
    ZerodhaCandles,
)


class RecordedKiteAPI:
    """A stand-in for `ZerodhaAPI` that answers every request with one recorded candle response.

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
        """Records a GET request and answers it with recorded candles.

        Args:
            url (str): The URL the downloader asked for.
            params (dict): The query parameters it sent.

        Returns:
            dict: The response envelope, with the candles under `data`.
        """
        self.requests.append((url, params))
        return {
            'status_code': 200,
            'data': {
                'candles': [
                    [
                        '2026-09-11T09:15:00+0530',
                        1285.0,
                        1291.0,
                        1283.6,
                        1290.5,
                        225000,
                        128846500,
                    ],
                    [
                        '2026-09-11T09:20:00+0530',
                        1290.5,
                        1292.2,
                        1288.1,
                        1289.0,
                        98500,
                        128901000,
                    ],
                ],
            },
        }


class FetchingFiveMinuteBarsExample:
    """Asks for one window of five minute bars and prints the request and the bars.

    Attributes:
        api (RecordedKiteAPI): The stand-in Kite API.
        candles (ZerodhaCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedKiteAPI()
        self.candles = object.__new__(ZerodhaCandles)
        self.candles._api = self.api

    def run(self):
        """Fetches the window, parses it and prints what was sent and what came back.

        Returns:
            None: This method returns nothing.
        """
        payload = self.candles.fetch_candles(
            '13368834',
            '5minute',
            datetime.date(2026, 9, 11),
            datetime.date(2026, 9, 11),
        )
        url, parameters = self.api.requests[0]
        print(f'Requested: {url}')
        print(f'Parameters: {parameters}')
        print(f'Candles in the payload: {len(payload["candles"])}')
        bars = self.candles.parse_response(payload, '5minute')
        for bar in bars:
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'{bar_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')
        print(f'Kite name for 1minute: {ZerodhaCandles.INTERVALS["1minute"]}')


if __name__ == '__main__':
    FetchingFiveMinuteBarsExample().run()
