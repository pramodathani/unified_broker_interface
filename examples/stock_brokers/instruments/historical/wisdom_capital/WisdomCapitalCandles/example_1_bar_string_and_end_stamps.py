"""Takes a market data token, fetches one window of RELIANCE one minute bars from Wisdom Capital, and turns the platform's bar string into bars.

Wisdom Capital runs Symphony's XTS platform, whose chart endpoint refuses the interactive trading token and wants a separate market data token. `after_relogin` takes that token from the API class, which is also what the constructor does, so the program calls it once to arm the downloader. The request then carries the token in its `authorization` header, the segment number and instrument id from the identifier `1|2885`, the window in the platform's own `Sep 11 2026 000000` format, and the bar length in seconds.

The answer is one string, bars separated by commas and fields by pipes. Each timestamp needs two corrections: it counts seconds as though India time were UTC, and it names the bar's last second rather than its first. So `1789031759`, which reads as 09:15:59 on 2026-09-10, is the one minute bar that opened at 09:15 India time. Read as a five minute bar, the same stamp would open four minutes earlier, at 09:11.

A `WisdomCapitalCandles` constructor opens a PostgreSQL connection and logs in, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and gives it a stand-in for `WisdomCapitalAPI`. The stand-in hands out a fixed market data token, records the request, and answers with a bar string shaped like the one the live one minute feed returned, wrapped in the `status_code` and `data` envelope the real API class returns, including the platform's own misspelled key `dataReponse`.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/wisdom_capital/WisdomCapitalCandles/example_1_bar_string_and_end_stamps.py
"""

import datetime

from stock_brokers.instruments.historical.wisdom_capital import (
    WisdomCapitalCandles,
)


class RecordedWisdomCapitalAPI:
    """A stand-in for `WisdomCapitalAPI` with a fixed market data token and one recorded bar string.

    Attributes:
        requests (list): The (url, headers, parameters) triples it was asked for.
    """

    def __init__(self):
        """Builds the stand-in with no requests recorded.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def replace_market_data_session(self, stale_access_token=None):
        """Hands out the market data session in force.

        Args:
            stale_access_token (str | None): A token that was refused, or None when none was.

        Returns:
            dict: The session's `access_token` and `user_id`.
        """
        return {
            'access_token': 'market-data-token-1',
            'user_id': 'WC1001',
        }

    def get(self, url, headers=None, params=None):
        """Records a GET request and answers it with two bars.

        Args:
            url (str): The URL the downloader asked for.
            headers (dict): The headers it sent.
            params (dict): The query parameters it sent.

        Returns:
            dict: The response envelope, with the platform's result under `data`.
        """
        self.requests.append((url, headers, params))
        return {
            'status_code': 200,
            'data': {
                'dataReponse': '1789031759|1279.5|1285.3|1279.5|1283.2|149743|0|,1789031819|1283.2|1284.0|1282.0|1283.0|51743|0|',
            },
        }


class BarStringAndEndStampsExample:
    """Arms the downloader with a market data token, fetches one window and parses it.

    Attributes:
        api (RecordedWisdomCapitalAPI): The stand-in Wisdom Capital API.
        candles (WisdomCapitalCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in API without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.api = RecordedWisdomCapitalAPI()
        self.candles = object.__new__(WisdomCapitalCandles)
        self.candles._api = self.api
        self.candles._empty_streak = 0

    def run(self):
        """Takes the token, fetches 2026-09-10 and prints the request and the bars.

        Returns:
            None: This method returns nothing.
        """
        self.candles.after_relogin()
        day = datetime.date(2026, 9, 10)
        payload = self.candles.fetch_candles('1|2885', '1minute', day, day)
        url, headers, parameters = self.api.requests[0]
        print(f'Requested {url}')
        print(f'  headers: {headers}')
        print(f'  parameters: {parameters}')
        print(f'  answer: {payload}')
        for bar in self.candles.parse_response(payload, '1minute'):
            bar_time, open_price, high, low, close, volume, open_interest = bar
            print(f'  {bar_time.isoformat()} open {open_price} high {high} low {low} close {close} volume {volume} oi {open_interest}')
        first_as_five_minutes = self.candles.parse_response(payload, '5minute')[0][0]
        print(f'The first stamp read as a five minute bar opens at {first_as_five_minutes.isoformat()}')


if __name__ == '__main__':
    BarStringAndEndStampsExample().run()
