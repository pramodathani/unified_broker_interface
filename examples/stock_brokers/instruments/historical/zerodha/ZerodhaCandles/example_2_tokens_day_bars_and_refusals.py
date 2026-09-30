"""Reads what a Kite instrument token says about its instrument, collapses a day bar onto its trading date, and shows an expired contract being refused.

Kite packs the exchange segment into the low byte of every instrument token and the exchange's own token into the bits above it, so RELIANCE on NSE is 738561, which is 2885 shifted left by eight bits with segment 1 in the low byte. `series_context` and `exchange_token` read that without any session, because they are a classmethod and a staticmethod. The program reads three tokens: NSE cash RELIANCE, the NIFTY 50 index (segment 9, which holds both exchanges' indices, so no exchange is named) and a token whose segment code Kite does not use.

It then parses a day bar stamped midnight India time, which `daily_bar_time` leaves on the same date, and skips a candle that is too short to read. Finally it fetches from a stand-in for `ZerodhaAPI` that raises the `ZerodhaAPIException` Kite's `invalid token` answer produces, which is what an instrument that has left the instrument dump gets. `fetch_candles` turns that into `CandleInstrumentUnknown`, the signal that retires the series rather than retrying it. The downloader is built without its constructor, as in `test_runs/candle_parse.py`, so no database connection is opened and no login happens.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/zerodha/ZerodhaCandles/example_2_tokens_day_bars_and_refusals.py
"""

import datetime

from stock_brokers.api.zerodha import (
    ZerodhaAPIException,
)
from stock_brokers.instruments.historical.base import (
    CandleInstrumentUnknown,
)
from stock_brokers.instruments.historical.zerodha import (
    ZerodhaCandles,
)


class RefusingKiteAPI:
    """A stand-in for `ZerodhaAPI` that refuses every request the way Kite refuses an expired contract."""

    def get(self, url, params=None):
        """Refuses a GET request with Kite's invalid token error.

        Args:
            url (str): The URL the downloader asked for.
            params (dict): The query parameters it sent.

        Returns:
            dict: Never returns.

        Raises:
            ZerodhaAPIException: Always, with Kite's `InputException` code.
        """
        raise ZerodhaAPIException(code='InputException', message='invalid token')


class TokensDayBarsAndRefusalsExample:
    """Reads tokens, parses a day bar and handles a refused window.

    Attributes:
        candles (ZerodhaCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the refusing stand-in without opening a database connection.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(ZerodhaCandles)
        self.candles._api = RefusingKiteAPI()

    def show_tokens(self):
        """Prints what each of three tokens says about its instrument.

        Returns:
            None: This method returns nothing.
        """
        tokens = [
            '738561',
            '256265',
            '738560',
        ]
        for token in tokens:
            context = ZerodhaCandles.series_context(token)
            if context.segments:
                segments = f'{len(context.segments)} segments starting {context.segments[0]}'
            else:
                segments = 'any segment'
            print(f'{token}: exchange {context.exchange}, {segments}, exchange token {context.exchange_token}')
        print(f'Exchange token inside 738561: {ZerodhaCandles.exchange_token("738561")}')

    def show_day_bars(self):
        """Parses a day bar and a candle too short to read.

        Returns:
            None: This method returns nothing.
        """
        payload = {
            'candles': [
                [
                    '2026-09-11T00:00:00+0530',
                    1267.0,
                    1267.4,
                    1253.0,
                    1257.5,
                    8777736,
                ],
                [
                    '2026-09-12T00:00:00+0530',
                    1257.5,
                ],
            ],
        }
        bars = self.candles.parse_response(payload, 'day')
        print(f'Day bars read: {len(bars)} of {len(payload["candles"])}')
        print(f'Day bar time: {bars[0][0].isoformat()}, close {bars[0][4]}, open interest {bars[0][6]}')

    def show_refusal(self):
        """Fetches a window of an expired contract and prints how the refusal is classified.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.candles.fetch_candles(
                '13368834',
                'day',
                datetime.date(2026, 1, 1),
                datetime.date(2026, 9, 11),
            )
        except CandleInstrumentUnknown as error:
            print(f'Refused as {type(error).__name__}: {error}')

    def run(self):
        """Runs the three parts in turn.

        Returns:
            None: This method returns nothing.
        """
        self.show_tokens()
        self.show_day_bars()
        self.show_refusal()


if __name__ == '__main__':
    TokensDayBarsAndRefusalsExample().run()
