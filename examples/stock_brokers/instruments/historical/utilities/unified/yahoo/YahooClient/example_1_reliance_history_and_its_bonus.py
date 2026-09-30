"""Reads RELIANCE's daily history from Yahoo Finance through `YahooClient`, and finds its 1:1 bonus among the listed events.

`YahooClient.history` asks yfinance for one ticker's whole daily history, with prices not adjusted for dividends and with corporate actions included, and returns two dictionaries: Yahoo's close by date, and the ratio of every split or bonus Yahoo lists, by its ex-date. RELIANCE went ex for a 1:1 bonus on 2024-10-28, which Yahoo lists as a ratio of 2.0. Days without an event carry 0 in the `Stock Splits` column and are left out, and a day with no close is left out of the closes.

The example runner routes all HTTP through a dead proxy, and Yahoo must never be contacted from here, so the program replaces the `yf` module inside `yahoo` with a stand-in whose `Ticker(...).history(...)` returns a small pandas frame shaped like the one yfinance returns, labelled Asia/Kolkata as Yahoo labels `.NS` tickers. The stand-in also records the arguments it was asked with. Before the request, `pace` spaces requests about a second apart; the client has sent nothing yet, so it does not wait, and the program shows only that `last_request` moved on, never a duration. It then sets `last_request` back to 0.0, which tells the client its last request was long ago, so the history call does not wait the second that `pace` would otherwise insert after the one just shown; a real caller leaves the attribute alone.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/yahoo/YahooClient/example_1_reliance_history_and_its_bonus.py
"""

import pandas

from stock_brokers.instruments.historical.utilities.unified import yahoo
from stock_brokers.instruments.historical.utilities.unified.yahoo import (
    YahooClient,
)


class StandInTicker:
    """A stand-in for `yfinance.Ticker` that returns a recorded-looking daily frame.

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
        """Returns five days of RELIANCE around its bonus.

        Args:
            period (str): How much history to return.
            auto_adjust (bool): Whether to adjust prices for dividends.
            actions (bool): Whether to include dividends and splits.

        Returns:
            pandas.DataFrame: Rows indexed by date, with Close, Dividends and Stock Splits columns.
        """
        self.requests.append(f'{self.symbol} period={period} auto_adjust={auto_adjust} actions={actions}')
        dates = pandas.to_datetime(
            [
                '2024-10-23',
                '2024-10-24',
                '2024-10-25',
                '2024-10-28',
                '2024-10-29',
            ]
        )
        frame = pandas.DataFrame(
            {
                'Close': [
                    1370.35,
                    1360.9,
                    1331.4,
                    1333.3,
                    float('nan'),
                ],
                'Dividends': [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                ],
                'Stock Splits': [
                    0.0,
                    0.0,
                    0.0,
                    2.0,
                    0.0,
                ],
            },
            index=dates.tz_localize('Asia/Kolkata'),
        )
        return frame


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


class RelianceHistoryExample:
    """Reads RELIANCE.NS through the stand-in and prints the closes and events.

    Attributes:
        yfinance (StandInYfinance): The stand-in yfinance module.
        client (YahooClient): The client being shown.
    """

    def __init__(self):
        """Installs the stand-in and builds the client.

        Returns:
            None: This method returns nothing.
        """
        self.yfinance = StandInYfinance()
        yahoo.yf = self.yfinance
        self.client = YahooClient()

    def run(self):
        """Paces once, reads the history and prints it.

        Returns:
            None: This method returns nothing.
        """
        print(f'last_request before any request: {self.client.last_request}')
        self.client.pace()
        print(f'last_request moved on after pace: {self.client.last_request > 0}')
        self.client.last_request = 0.0
        closes, events = self.client.history('RELIANCE.NS')
        print(f'Requests sent: {self.yfinance.requests}')
        for day, close in closes.items():
            print(f'  {day} close {close}')
        for day, ratio in events.items():
            print(f'Listed event: {day} ratio {ratio}')


if __name__ == '__main__':
    RelianceHistoryExample().run()
