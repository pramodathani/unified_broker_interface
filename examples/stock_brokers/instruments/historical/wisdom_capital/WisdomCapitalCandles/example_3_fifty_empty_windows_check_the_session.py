"""Shows what Wisdom Capital's downloader does after fifty empty windows in a row: it asks about an instrument that always has bars before deciding the session is dead.

The XTS platform answers an unknown instrument, a window before the history begins and an expired market data token in exactly the same way, with an empty bar string. So after fifty empty windows `fetch_candles` asks about NSE cash RELIANCE for the past week. If that is empty too it takes a fresh market data token, handing the refused one back so a token another process already replaced is recognised, and asks once more. Only if the second answer is empty as well does it raise `CandleAuthenticationError` and stop the broker.

The program runs two stand-ins for `WisdomCapitalAPI` through this. In the first, the market data token has expired: every answer is empty until a new token is taken, after which RELIANCE has bars, so the fiftieth window returns normally with the streak reset. In the second, the platform answers everything empty whatever the token, so the fiftieth window raises. The stand-ins count requests and record which stale token each replacement was given; the canary's window depends on today's date, so it is not printed.

A `WisdomCapitalCandles` constructor opens a PostgreSQL connection and logs in, so the program builds the object without running its constructor, as `test_runs/candle_parse.py` does, and supplies the rate limiter and logger the constructor would have made. The limiter is set to a thousand requests a second so the program does not wait, and the logger is silent so the warning the check logs does not clutter the output.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/wisdom_capital/WisdomCapitalCandles/example_3_fifty_empty_windows_check_the_session.py
"""

import datetime
import logging

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
    RateLimiter,
)
from stock_brokers.instruments.historical.wisdom_capital import (
    WisdomCapitalCandles,
)


class EmptyAnsweringAPI:
    """A stand-in for `WisdomCapitalAPI` that answers empty until its token is replaced, or for ever.

    Attributes:
        recovers_after_new_token (bool): True when a fresh token makes the canary answer with bars.
        tokens_issued (int): How many market data tokens it has handed out.
        stale_tokens (list): The stale token each replacement was given.
        requests (int): How many chart requests it answered.
    """

    def __init__(self, recovers_after_new_token):
        """Builds the stand-in.

        Args:
            recovers_after_new_token (bool): True when a fresh token makes the canary answer with bars.

        Returns:
            None: This method returns nothing.
        """
        self.recovers_after_new_token = recovers_after_new_token
        self.tokens_issued = 0
        self.stale_tokens = []
        self.requests = 0

    def replace_market_data_session(self, stale_access_token=None):
        """Hands out a new market data token.

        Args:
            stale_access_token (str | None): The token that was refused, or None when none was.

        Returns:
            dict: The session's `access_token` and `user_id`.
        """
        self.tokens_issued += 1
        self.stale_tokens.append(stale_access_token)
        return {
            'access_token': f'market-data-token-{self.tokens_issued}',
            'user_id': 'WC1001',
        }

    def get(self, url, headers=None, params=None):
        """Answers a chart request, with bars only for the canary on a fresh token when it recovers.

        Args:
            url (str): The URL the downloader asked for.
            headers (dict): The headers it sent.
            params (dict): The query parameters it sent.

        Returns:
            dict: The response envelope, with the platform's result under `data`.
        """
        self.requests += 1
        bars = ''
        is_canary = params['exchangeInstrumentID'] == '2885'
        fresh_token = headers['authorization'] != 'market-data-token-1'
        if self.recovers_after_new_token and is_canary and fresh_token:
            bars = '1789031759|1279.5|1285.3|1279.5|1283.2|149743|0|'
        return {
            'status_code': 200,
            'data': {
                'dataReponse': bars,
            },
        }


class FiftyEmptyWindowsCheckTheSessionExample:
    """Runs fifty empty windows against a recovering platform and against a dead one."""

    def build_downloader(self, api):
        """Builds a downloader around a stand-in API without opening a database connection.

        Args:
            api (EmptyAnsweringAPI): The stand-in API.

        Returns:
            WisdomCapitalCandles: The downloader, holding its first market data token.
        """
        candles = object.__new__(WisdomCapitalCandles)
        candles._api = api
        candles._empty_streak = 0
        candles._relogin_used = False
        candles._limiter = RateLimiter(1000.0)
        candles._logger = logging.getLogger('example.wisdom_capital')
        candles._logger.disabled = True
        candles.after_relogin()
        return candles

    def walk_fifty_empty_windows(self, description, api):
        """Asks for fifty expired contracts' windows and prints how the fiftieth ends.

        Args:
            description (str): What the stand-in pretends.
            api (EmptyAnsweringAPI): The stand-in API.

        Returns:
            None: This method returns nothing.
        """
        candles = self.build_downloader(api)
        day = datetime.date(2025, 6, 2)
        print(description)
        try:
            for instrument_number in range(50):
                candles.fetch_candles(f'2|{40000 + instrument_number}', '5minute', day, day)
            print('  the fiftieth window returned normally')
        except CandleAuthenticationError as error:
            print(f'  {type(error).__name__}: {error}')
        print(f'  chart requests: {api.requests}')
        print(f'  market data tokens issued: {api.tokens_issued}, stale tokens handed back: {api.stale_tokens}')

    def run(self):
        """Runs the recovering platform, then the dead one.

        Returns:
            None: This method returns nothing.
        """
        self.walk_fifty_empty_windows('Expired market data token:', EmptyAnsweringAPI(True))
        self.walk_fifty_empty_windows('Platform answering nothing:', EmptyAnsweringAPI(False))


if __name__ == '__main__':
    FiftyEmptyWindowsCheckTheSessionExample().run()
