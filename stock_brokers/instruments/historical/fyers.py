"""
Fyers historical candle download.

Fyers is addressed by ticker rather than by token: the request carries `NSE:RELIANCE-EQ`, not the
fytoken the instrument master is keyed on, so the ticker is what the progress table stores.

Four things were settled against the live API on 2026-09-12 rather than taken from the
documentation, which is a JavaScript application rather than a page.

The endpoint answers at `api-t1.fyers.in/data/history`, and its authorization header is the
application id joined to the access token by a colon with no `Bearer` prefix - which is what this
project's `FyersAPI` already sends.

The range caps are stated in the refusal: one hundred days for every intraday resolution, three
hundred and sixty six for `1D`, `1W` and `1M`. They are refusals, not truncations.

Daily history reaches 2000: RELIANCE answers for every year from 2000 and `no_data` for 1995.

An empty window comes back as HTTP 200 with `s` holding `no_data`, so emptiness has to be read
from that field rather than from the status line. A candle row is six elements for cash and seven
for a derivative, the seventh being open interest, so it is read by length.

Fyers stamps a daily bar at midnight UTC where Kite stamps midnight India time - the same trading
day, five and a half hours apart - which is why day, week and month bars go through
`daily_bar_time` before they are stored.
"""

import datetime

from stock_brokers.instruments.historical.base import (BrokerCandles,
                                                       CandleAuthenticationError,
                                                       CandleBlocked,
                                                       CandleInstrumentUnknown,
                                                       CandleThrottled,
                                                       SeriesContext,
                                                       daily_bar_time,
                                                       is_intraday)
from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                             INDEX_SEGMENTS, segments_of)

HISTORICAL_URL = "https://api-t1.fyers.in/data/history"

# Fyers' codes for a session it will not accept: -8 token expired, -15 invalid token, -16 the
# server could not authenticate the token, -17 token invalid or expired. Fyers' own guidance for
# all four is to log in once and then surface the error rather than retry. The text of the
# messages is not stable enough to match on; -16 arrives as "Could not authenticate", which a text
# match would miss, and a download that carries on against a refused session sends about fifty
# refused requests a minute until Cloudflare bans the machine's address.
AUTHENTICATION_ERROR_CODES = {-8, -15, -16, -17}

# Phrases that identify Cloudflare's block page, which it serves with HTTP 429 in front of
# api-t1.fyers.in. The status alone cannot tell it apart from Fyers' JSON rate limit response.
# "cloudflare" by itself is deliberately not one of them: Cloudflare's ordinary outage pages say it
# too, and a passing 522 is not a reason to stop the broker.
BLOCK_PAGE_MARKERS = ("error 1015", "error code: 1015", "banned you temporarily")

class FyersCandles(BrokerCandles):
    """
    Downloads Fyers' historical candles.
    """

    BROKER_NAME = "fyers"

    # Stored name to Fyers' resolution code. Every one of these was confirmed to return bars;
    # Fyers serves a wider set of intraday resolutions than any other broker here.
    INTERVALS = {
        "1minute": "1",
        "2minute": "2",
        "3minute": "3",
        "5minute": "5",
        "10minute": "10",
        "15minute": "15",
        "20minute": "20",
        "30minute": "30",
        "45minute": "45",
        "60minute": "60",
        "120minute": "120",
        "180minute": "180",
        "240minute": "240",
        "day": "1D",
        "week": "1W",
        "month": "1M",
    }

    # Fyers states both caps in the refusal itself: "range_to cannot be 100 days greater than
    # range_from" for the intraday resolutions, and "Date range cannot exceed 366 days for 1D, 1W
    # and 1M". Asking for more is an HTTP 422, not a shortened answer.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 100,
        "2minute": 100,
        "3minute": 100,
        "5minute": 100,
        "10minute": 100,
        "15minute": 100,
        "20minute": 100,
        "30minute": 100,
        "45minute": 100,
        "60minute": 100,
        "120minute": 100,
        "180minute": 100,
        "240minute": 100,
        "day": 366,
        "week": 366,
        "month": 366,
    }

    # Fyers documents no rate for the history endpoint, so this is a conservative figure rather
    # than a published one. Raise it only after measuring.
    REQUESTS_PER_SECOND = 3.0
    REQUESTS_PER_DAY = None

    EARLIEST_AVAILABLE_DATE = datetime.date(2000, 1, 1)

    TOKEN_COLUMN = "symbol_ticker"
    TYPE_COLUMN = "exchange_instrument_type"
    EXPIRY_COLUMN = "expiry_date"

    def __init__(self, api=None):
        """
        Fyers candle downloader.

        - `api` is an authenticated `FyersAPI`. One is constructed when not supplied, which
          establishes a session if the stored one has expired.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session
            from stock_brokers.api.fyers import FyersAPI

            # Through ensure_session, so this shares the Redis lock and the login rate limiter
            # with any other process using ensure_session. A backfill runs for weeks and will be
            # alive across a token expiry.
            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = FyersAPI()
        self._api = api

    def instruments(self):
        """
        Every ticker Fyers has ever published, with the fields the queue's priority needs.

        Two translations happen here rather than in `priority_for`, because both are Fyers'
        vocabulary rather than this project's.

        Fyers names an instrument's kind with a number - 13 is a stock future, 15 a stock option -
        and the numbers are not stable enough across segments to be worth a lookup table when the
        ticker already says it plainly: it ends in `FUT` for a future and `CE` or `PE` for an
        option. And its expiry is epoch seconds rather than a date, which `priority_for` cannot
        read, so it is converted here. Without the conversion every expired contract would be
        queued as though it were live, ahead of cash intraday bars that are actually wanted.
        """
        query = f"""
            select distinct on (i."{self.TOKEN_COLUMN}")
                   i."{self.TOKEN_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
            order by i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        self._connection.commit()

        instruments = []
        for ticker, expiry in rows:
            upper = str(ticker).upper()
            if upper.endswith("FUT"):
                kind = "FUT"
            elif upper.endswith("CE") or upper.endswith("PE"):
                kind = "OPT"
            else:
                kind = "EQ"
            instruments.append((ticker, kind, self._expiry_date(expiry)))
        return instruments

    @staticmethod
    def _expiry_date(expiry):
        """
        Turn Fyers' epoch expiry into a date, or None when the instrument does not expire.

        - `expiry` is the `expiry_date` column, epoch seconds as text.
        """
        try:
            seconds = int(expiry)
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).date()

    # The exchange prefix of a Fyers ticker.
    EXCHANGES = {"NSE": "nse", "BSE": "bse", "MCX": "mcx", "NCDEX": "ncdex"}

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of a Fyers ticker.

        The price table names an instrument by its ticker, while the mapping keys Fyers by its
        numeric fytoken. The ticker is kept in the mapping as `order_symbol`, so that is what the
        series is matched on.

        Args:
            identifier (str): For example "NSE:RELIANCE-EQ" or "NSE:NIFTY50-INDEX".

        Returns:
            SeriesContext: The ticker, to be matched on `order_symbol`, with its exchange and segments.
        """
        ticker = str(identifier)
        exchange = cls.EXCHANGES.get(ticker.split(":", 1)[0])
        if exchange is None:
            return SeriesContext(ticker, match_on="order_symbol")
        upper = ticker.upper()
        if upper.endswith("-INDEX"):
            family = INDEX_SEGMENTS
        elif upper.endswith(("FUT", "CE", "PE")):
            family = DERIVATIVE_SEGMENTS
        else:
            family = CASH_SEGMENTS
        return SeriesContext(ticker, exchange, segments_of(exchange, family), "order_symbol")

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of Fyers candles.

        - `token` is the Fyers ticker, such as `NSE:RELIANCE-EQ`.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        parameters = {"symbol": token, "resolution": self.INTERVALS[interval], "date_format": "1",
                      "range_from": start_date.isoformat(), "range_to": end_date.isoformat(),
                      "cont_flag": "1", "oi_flag": "1"}

        try:
            response = self._api.get(url=HISTORICAL_URL, params=parameters)
        except Exception as exception:
            # A session error comes back as CandleAuthenticationError, and the base class logs in
            # once and asks for this window again. See `BrokerCandles._fetch_bars`.
            raise self._classify(exception) from exception

        return (response or {}).get("data") or {}

    @staticmethod
    def _classify(exception):
        """
        Decide what a Fyers refusal means for the series being downloaded.

        Fyers answers an unknown ticker with code -300, "Invalid symbol provided", which is the
        one that retires a series. Code -50 is its catch-all input error and is what a window
        wider than the cap returns, so it is a fault in this module rather than a dead instrument
        and is left to back off.

        The session codes are matched on the number Fyers sends, not on the wording. Cloudflare's
        block page is recognised before any 429, since it is served as one and must stop the
        broker rather than slow it down.

        - `exception` is what the API call raised.
        """
        text = str(exception)
        lowered = text.lower()
        code = getattr(exception, "code", None)
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None

        # Checked before anything mentioning 429, because the block page is itself a 429.
        if (any(marker in lowered for marker in BLOCK_PAGE_MARKERS)
                or (code == 429 and "cloudflare" in lowered)):
            return CandleBlocked(f"refused by Cloudflare in front of Fyers, which blocks the IP "
                                 f"address rather than the session: {text[:160]}")
        if code == -300 or "invalid symbol" in lowered or "-300" in text:
            return CandleInstrumentUnknown(text[:200])
        if (code in AUTHENTICATION_ERROR_CODES
                or "could not authenticate" in lowered
                or "token expired" in lowered
                or ("token" in lowered and "invalid" in lowered)
                or "unauthor" in lowered):
            return CandleAuthenticationError(text[:200])
        if (code == 429 or "too many requests" in lowered or "rate limit" in lowered
                or "request limit" in lowered or "429" in text):
            return CandleThrottled(text[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn Fyers' candle list into bars.

        An empty window is an HTTP 200 carrying `s` of `no_data`, which is read here and answered
        with no bars. A row is `[epoch, open, high, low, close, volume]` for a cash instrument and
        carries open interest as a seventh element for a derivative, so it is read by length.

        - `payload` is the decoded response body.
        - `interval` is the stored interval name.
        """
        payload = payload or {}
        status = payload.get("s")
        if status == "no_data":
            return []
        if status not in (None, "ok"):
            raise ValueError(f"fyers answered with s={status!r}: {str(payload)[:200]}")

        bars = []
        for candle in payload.get("candles") or []:
            if len(candle) < 6:
                continue
            bar_time = datetime.datetime.fromtimestamp(candle[0], datetime.timezone.utc)
            if not is_intraday(interval):
                # Fyers stamps a day bar at midnight UTC, which is the same trading day Kite
                # stamps at midnight India time. Normalised so the two can be compared.
                bar_time = daily_bar_time(bar_time)
            open_interest = candle[6] if len(candle) > 6 else None
            bars.append((bar_time, candle[1], candle[2], candle[3], candle[4], candle[5],
                         open_interest))
        return bars
