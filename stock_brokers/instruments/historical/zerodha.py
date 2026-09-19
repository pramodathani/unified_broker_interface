"""
Zerodha historical candle download.

Kite serves candles at `/instruments/historical/{token}/{interval}`, three requests a second, and
goes back to 2005 for daily bars on long listed equities. `oi=1` is always sent: for cash it
changes nothing, and for derivatives it adds open interest as a seventh element, so the response
is read by length rather than by fixed index.

Two behaviours are worth knowing. Kite caps how far one request may reach, and the cap differs by
interval - sixty days for minute bars, two thousand for daily - which is what makes a deep
backfill a walk rather than a single call. And an instrument that has left the current instrument
dump is refused with `invalid token` rather than an empty response, so an expired contract's
history is unreachable the moment it expires; the series is retired instead of retried.
"""

import datetime

from stock_brokers.instruments.historical.base import (BrokerCandles,
                                                       CandleAuthenticationError,
                                                       CandleInstrumentUnknown,
                                                       CandleThrottled,
                                                       SeriesContext,
                                                       daily_bar_time,
                                                       is_intraday)
from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                             INDEX_SEGMENTS, segments_of)

HISTORICAL_URL = "https://api.kite.trade/instruments/historical"

class ZerodhaCandles(BrokerCandles):
    """
    Downloads Zerodha's historical candles.
    """

    BROKER_NAME = "zerodha"

    # Stored name to the name Kite expects. Kite calls one minute bars simply "minute".
    INTERVALS = {
        "1minute": "minute",
        "3minute": "3minute",
        "5minute": "5minute",
        "10minute": "10minute",
        "15minute": "15minute",
        "30minute": "30minute",
        "60minute": "60minute",
        "day": "day",
    }

    # Verified against the live API: asking for more is refused with
    # "interval exceeds max limit: N days" rather than being truncated.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 60,
        "3minute": 100,
        "5minute": 100,
        "10minute": 100,
        "15minute": 200,
        "30minute": 200,
        "60minute": 400,
        "day": 2000,
    }

    # Kite documents three requests a second for historical candles, and publishes no daily cap.
    REQUESTS_PER_SECOND = 3.0
    REQUESTS_PER_DAY = None

    EARLIEST_AVAILABLE_DATE = datetime.date(2005, 1, 1)

    TOKEN_COLUMN = "instrument_token"
    TYPE_COLUMN = "instrument_type"
    EXPIRY_COLUMN = "expiry"

    def __init__(self, api=None):
        """
        Zerodha candle downloader.

        - `api` is an authenticated `ZerodhaAPI`. One is constructed when not supplied, which
          establishes a session if the stored one has expired.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session
            from stock_brokers.api.zerodha import ZerodhaAPI

            # Through ensure_session rather than straight to ZerodhaAPI, so this shares the Redis
            # lock and the rate limiter with any other process using ensure_session. Kite issues one
            # access token per session and a second login invalidates the first, and this process
            # runs for weeks - it will be alive across the overnight expiry, when another process may
            # be logging in too. Without the lock one of the two ends up holding a replaced token.
            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = ZerodhaAPI()
        self._api = api

    # Kite packs the exchange segment into the low byte of every instrument token, with the exchange
    # token in the bits above it: RELIANCE is 738561 = 2885 << 8 | 1. Checked against all 110,290
    # tokens in the 2026-09-13 instrument file, where token >> 8 equals exchange_token for every row.
    SEGMENT_CODES = {
        1: ("nse", CASH_SEGMENTS),         # NSE
        2: ("nse", DERIVATIVE_SEGMENTS),   # NFO
        3: ("nse", DERIVATIVE_SEGMENTS),   # CDS
        4: ("bse", CASH_SEGMENTS),         # BSE
        5: ("bse", DERIVATIVE_SEGMENTS),   # BFO
        6: ("bse", DERIVATIVE_SEGMENTS),   # BCD
        7: ("mcx", DERIVATIVE_SEGMENTS),   # MCX
        9: (None, INDEX_SEGMENTS),         # INDICES, which holds both exchanges' indices
        12: ("nse", DERIVATIVE_SEGMENTS),  # NCO
    }

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of a Kite instrument token.

        Args:
            identifier (str): A Kite instrument token, for example "738561".

        Returns:
            SeriesContext: The token itself, with the exchange and segments its low byte names.
        """
        token = str(identifier)
        exchange, family = cls.SEGMENT_CODES.get(int(token) & 255, (None, None))
        if family is None:
            return SeriesContext(token)
        if exchange is None:
            return SeriesContext(token, None, segments_of(["nse", "bse"], family))
        return SeriesContext(token, exchange, segments_of([exchange], family),
                             exchange_token=cls.exchange_token(token))

    @staticmethod
    def exchange_token(identifier):
        """
        The exchange's own token inside a Kite instrument token.

        Args:
            identifier (str): A Kite instrument token.

        Returns:
            str: The exchange token, for example "2885" for 738561.
        """
        return str(int(identifier) >> 8)

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of Kite candles.

        - `token` is the Kite instrument token.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        url = f"{HISTORICAL_URL}/{token}/{self.INTERVALS[interval]}"
        parameters = {"from": start_date.isoformat(), "to": end_date.isoformat(), "oi": 1}

        try:
            response = self._api.get(url=url, params=parameters)
        except Exception as exception:
            raise self._classify(exception) from exception

        return (response or {}).get("data") or {}

    @staticmethod
    def _classify(exception):
        """
        Decide what a Kite error means for the series being downloaded.

        The distinction that matters is between "this instrument will never work", which retires
        the series, and everything else, which is retried with backoff. Kite reports the first as
        an InputException naming an invalid token.

        - `exception` is what the API call raised.
        """
        text = str(exception).lower()

        if "invalid token" in text or "invalid instrument" in text:
            return CandleInstrumentUnknown(str(exception)[:200])
        if "too many requests" in text or "429" in text:
            return CandleThrottled(str(exception)[:200])
        if ("tokenexception" in text or "invalid api" in text
                or "incorrect `api_key`" in text or "access_token" in text):
            return CandleAuthenticationError(str(exception)[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn Kite's candle list into bars.

        Kite returns `[timestamp, open, high, low, close, volume]`, and a seventh element for
        open interest when `oi=1` applies. Read by length: a cash instrument simply has six.

        - `payload` is the `data` object from the response.
        - `interval` is the stored interval name, which decides whether the bar time is left
          alone or collapsed onto its trading date.
        """
        bars = []
        for candle in (payload or {}).get("candles") or []:
            if len(candle) < 6:
                continue
            # Kite sends ISO-8601 with an offset, "2026-09-01T00:00:00+0530". Parsed here rather
            # than left as text so the stored bar time and the watermark read back from Postgres
            # are the same kind of thing and can be compared.
            try:
                bar_time = datetime.datetime.fromisoformat(candle[0])
            except (TypeError, ValueError):
                continue
            if not is_intraday(interval):
                # Kite already stamps midnight India time, so this changes nothing for Zerodha.
                # It is applied anyway so that every broker's day bar is normalised in the same
                # place, and a reader does not have to know Kite's convention to trust the row.
                bar_time = daily_bar_time(bar_time)
            open_interest = candle[6] if len(candle) > 6 else None
            bars.append((bar_time, candle[1], candle[2], candle[3], candle[4],
                         candle[5], open_interest))
        return bars
