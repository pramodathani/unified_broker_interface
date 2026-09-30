"""Tries the Yahoo ticker forms for a BSE share in order, passing over a stub, the way the factor builder does.

Yahoo keeps many BSE tickers only as stubs: RELIANCE.BO returns two rows. So a BSE instrument is tried as SYMBOL.BO first, then as its BSE scrip code, 500325.BO, and the first form whose closes cover at least 80% of the stored raw trading days is used. `ticker_forms` lists the forms and `coverage` measures each one; `YahooClient.history` fetches them. A ticker Yahoo has nothing for comes back as an empty frame, which `history` turns into two empty dictionaries.

Scrip code tickers come back labelled America/New_York while still carrying Indian trading dates, so `history` reads the date straight off each timestamp rather than converting it; the output shows 2024-10-28 staying 2024-10-28. The example runner routes all HTTP through a dead proxy, and Yahoo must never be contacted from here, so the program replaces the `yf` module inside `yahoo` with a stand-in whose `Ticker(...).history(...)` returns small pandas frames shaped like yfinance's. Before each request it sets the client's `last_request` back to 0.0, which tells the client its last request was long ago, so `pace` does not wait the second it would normally insert between requests; a real caller leaves the attribute alone.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/yahoo/YahooClient/example_2_trying_ticker_forms_for_a_bse_share.py
"""

import datetime

import pandas

from stock_brokers.instruments.historical.utilities.unified import yahoo
from stock_brokers.instruments.historical.utilities.unified.yahoo import (
    YahooClient,
)


class StandInTicker:
    """A stand-in for `yfinance.Ticker` that returns a recorded-looking frame per ticker.

    Attributes:
        symbol (str): The ticker asked for.
        requests (list): Where each history request's arguments are recorded.
    """

    def __init__(self, symbol, requests):
        """Remembers the ticker and where to record requests.

        Args:
            symbol (str): The ticker asked for.
            requests (list): Where each history request's arguments are recorded.

        Returns:
            None: This method returns nothing.
        """
        self.symbol = symbol
        self.requests = requests

    def history(self, period, auto_adjust, actions):
        """Returns the frame recorded for this ticker.

        Args:
            period (str): How much history to return.
            auto_adjust (bool): Whether to adjust prices for dividends.
            actions (bool): Whether to include dividends and splits.

        Returns:
            pandas.DataFrame: Rows indexed by date, with Close and Stock Splits columns, empty when Yahoo has nothing.
        """
        self.requests.append(self.symbol)
        if self.symbol == 'RELIANCE.BO':
            return self.frame(
                [
                    '2024-10-28',
                    '2024-10-29',
                ],
                'Asia/Kolkata',
            )
        if self.symbol == '500325.BO':
            return self.frame(
                [
                    '2024-10-22',
                    '2024-10-23',
                    '2024-10-24',
                    '2024-10-25',
                    '2024-10-28',
                ],
                'America/New_York',
            )
        return pandas.DataFrame()

    def frame(self, dates, timezone_name):
        """Builds a frame with a steady close and a 1:1 bonus on 2024-10-28.

        Args:
            dates (list): The trading dates, as ISO strings.
            timezone_name (str): The time zone Yahoo labels the index with.

        Returns:
            pandas.DataFrame: The frame.
        """
        closes = []
        splits = []
        for date_text in dates:
            closes.append(1333.3)
            if date_text == '2024-10-28':
                splits.append(2.0)
            else:
                splits.append(0.0)
        index = pandas.to_datetime(dates).tz_localize(timezone_name)
        return pandas.DataFrame(
            {
                'Close': closes,
                'Stock Splits': splits,
            },
            index=index,
        )


class StandInYfinance:
    """A stand-in for the `yfinance` module, offering only `Ticker`.

    Attributes:
        requests (list): Every history request made through it.
    """

    def __init__(self):
        """Starts with no requests.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def Ticker(self, symbol):
        """Builds a stand-in ticker, under the name yfinance uses.

        Args:
            symbol (str): The Yahoo ticker.

        Returns:
            StandInTicker: The ticker.
        """
        return StandInTicker(symbol, self.requests)


class TryingTickerFormsExample:
    """Tries each ticker form for RELIANCE on BSE and keeps the first that covers the raw history.

    Attributes:
        yfinance (StandInYfinance): The stand-in yfinance module.
        client (YahooClient): The client being shown.
        raw_days (list): The dates the stored raw bars have.
    """

    def __init__(self):
        """Installs the stand-in and builds the client.

        Returns:
            None: This method returns nothing.
        """
        self.yfinance = StandInYfinance()
        yahoo.yf = self.yfinance
        self.client = YahooClient()
        self.raw_days = [
            datetime.date(2024, 10, 22),
            datetime.date(2024, 10, 23),
            datetime.date(2024, 10, 24),
            datetime.date(2024, 10, 25),
            datetime.date(2024, 10, 28),
        ]

    def run(self):
        """Walks the forms and prints each one's coverage.

        Returns:
            None: This method returns nothing.
        """
        forms = yahoo.ticker_forms('bse', 'RELIANCE', '500325', listed_on_nse=True)
        print(f'Forms to try: {forms}')
        for ticker, kind in forms:
            self.client.last_request = 0.0
            closes, events = self.client.history(ticker)
            share = yahoo.coverage(closes, self.raw_days)
            print(f'{ticker} ({kind}): {len(closes)} closes, coverage {share:.1f}, events {events}')
            if share >= yahoo.MINIMUM_COVERAGE:
                print(f'Using {ticker}')
                break
        self.client.last_request = 0.0
        closes, events = self.client.history('NOSUCHSHARE.BO')
        print(f'A ticker Yahoo has nothing for: closes {closes}, events {events}')
        print(f'Requests sent: {self.yfinance.requests}')

if __name__ == '__main__':
    TryingTickerFormsExample().run()
