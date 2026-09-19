"""
IND Money historical candle download.

The endpoint is `api.indstocks.com/market/historical/<interval>` - the interval is a path segment,
so each interval is a different URL - and it takes the window as epoch **milliseconds** while
answering in epoch **seconds**. That asymmetry reads like a documentation error and is genuine.

An instrument is named by a scrip code, an exchange prefix joined to IND Money's security id by an
underscore, and the prefix is not the exchange the instrument master names. Measured on
2026-09-12: NSE cash is `NSE_2885`, BSE cash is `BSE_500325`, an index is `NSE_40000001`, and an
NSE derivative is `NFO_68777`. Asking for `NSE_68777` - the exchange the master actually records
for that contract - is accepted and answers **zero bars**, silently, which is the worst possible
failure mode and the reason the prefix is derived from the segment here rather than copied from
the exchange column.

BSE derivatives are not served at all: both `BFO_` and `BSE_` are refused with "Invalid scrip
codes", so they are left out of the queue rather than registered and retired one request each.

The window cap is a truncation rather than a refusal, and it is measured in trading days: minute
intervals up to thirty return the newest five trading days of whatever window is asked for, the
hourly ones eleven, and daily, weekly and monthly one year. Asking wider does not fail, it
quietly returns less - so `MAXIMUM_WINDOW_DAYS` here is not a documented limit but the point past
which data would be lost without any sign of it. The truncation is relative to the window rather
than to today, which is what makes the backward walk possible at all.

IND Money publishes no open interest on any interval, so that column is left null.

The endpoint will answer about five instruments in one call. That is not used: the downloader
visits one series at a time, and taking five would need a second path through the base class for
one broker. The cost is real and worth recording - IND Money caps data requests at one hundred
thousand a day, so asking one at a time makes this backfill five times longer than it needs to be.
If that becomes the binding constraint, batching is the first thing to do.
"""

import datetime

from stock_brokers.instruments.historical.base import (INDIA_TIMEZONE,
                                                       BrokerCandles,
                                                       CandleAuthenticationError,
                                                       CandleInstrumentUnknown,
                                                       CandleThrottled,
                                                       SeriesContext,
                                                       daily_bar_time,
                                                       is_intraday)
from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                             INDEX_SEGMENTS, segments_of)

HISTORICAL_URL = "https://api.indstocks.com/market/historical"

class IndMoneyCandles(BrokerCandles):
    """
    Downloads IND Money's historical candles.
    """

    BROKER_NAME = "indmoney"

    # Stored name to IND Money's path segment. Every one of these was confirmed to return bars.
    INTERVALS = {
        "1minute": "1minute",
        "2minute": "2minute",
        "3minute": "3minute",
        "5minute": "5minute",
        "10minute": "10minute",
        "15minute": "15minute",
        "30minute": "30minute",
        "60minute": "60minute",
        "120minute": "120minute",
        "180minute": "180minute",
        "240minute": "240minute",
        "day": "1day",
        "week": "1week",
        "month": "1month",
    }

    # Measured, not documented, and these are truncation points rather than refusals: a window
    # wider than this returns its newest portion and says nothing about the rest. Seven calendar
    # days are five trading days, fifteen are eleven, and a year is what the coarse intervals give.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 7,
        "2minute": 7,
        "3minute": 7,
        "5minute": 7,
        "10minute": 7,
        "15minute": 7,
        "30minute": 7,
        "60minute": 15,
        "120minute": 15,
        "180minute": 15,
        "240minute": 15,
        "day": 365,
        "week": 365,
        "month": 365,
    }

    # Documented as five a second. Twenty requests at three a second passed without a refusal,
    # while an unpaced burst was throttled within six, so three is what is used. The daily budget
    # is the limit that actually decides how long this backfill takes.
    REQUESTS_PER_SECOND = 3.0
    REQUESTS_PER_DAY = 100000

    # Daily bars answer for 2014 and are empty for 2012, so the history begins between the two.
    # The exact date does not matter: the walk stops on three empty windows either way.
    EARLIEST_AVAILABLE_DATE = datetime.date(2013, 1, 1)

    TOKEN_COLUMN = "security_id"
    TYPE_COLUMN = "sem_exch_instrument_type"
    EXPIRY_COLUMN = "expiry_date"

    def __init__(self, api=None):
        """
        IND Money candle downloader.

        - `api` is an authenticated `INDMoneyAPI`. One is constructed when not supplied, which
          establishes a session if the stored one has expired.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session
            from stock_brokers.api.indmoney import INDMoneyAPI

            # Through ensure_session, so this shares the Redis lock and the login rate limiter
            # with any other process using ensure_session. A backfill runs for weeks and will be
            # alive across a token expiry.
            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = INDMoneyAPI()
        self._api = api

    def instruments(self):
        """
        Every instrument IND Money has published, named the way the chart endpoint needs.

        The scrip code's prefix comes from the segment rather than from the exchange column,
        because a derivative's exchange is recorded as NSE while the endpoint wants NFO - and
        asking with NSE is accepted and answers nothing at all, so getting this wrong would show
        up as an instrument with no history rather than as an error.

        BSE derivatives are left out: the endpoint refuses every prefix tried for them.

        The expiry is converted from IND Money's `09/29/2026 14:00` to a date here, because
        `priority_for` reads dates and would otherwise treat every expired contract as live and
        queue it ahead of the cash bars that are actually wanted.
        """
        query = f"""
            select distinct on (i.exch, i.segment, i."{self.TOKEN_COLUMN}")
                   i.exch, i.segment, i."{self.TOKEN_COLUMN}",
                   i."{self.TYPE_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
            order by i.exch, i.segment, i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        self._connection.commit()

        instruments = []
        for exchange, segment, token, instrument_type, expiry in rows:
            prefix = self._scrip_prefix(exchange, segment)
            if prefix is None:
                continue
            instruments.append((f"{prefix}_{token}", instrument_type, self._expiry_date(expiry)))
        return instruments

    @staticmethod
    def _scrip_prefix(exchange, segment):
        """
        The scrip code prefix for one instrument, or None when IND Money will not chart it.

        - `exchange` is the `exch` column, NSE or BSE.
        - `segment` is the `segment` column: `D` for derivatives, `E` for cash, and the index's
          own name for an index.
        """
        if segment == "D":
            return "NFO" if exchange == "NSE" else None
        return exchange

    @staticmethod
    def _expiry_date(expiry):
        """
        Turn IND Money's `09/29/2026 14:00` expiry into a date, or None when there is none.

        - `expiry` is the `expiry_date` column.
        """
        if not expiry:
            return None
        try:
            return datetime.datetime.strptime(str(expiry)[:10], "%m/%d/%Y").date()
        except ValueError:
            return None

    # The scrip code's prefix names the exchange, as built in `instruments`.
    PREFIXES = {
        "NSE": ("nse", CASH_SEGMENTS + INDEX_SEGMENTS),
        "BSE": ("bse", CASH_SEGMENTS + INDEX_SEGMENTS),
        "NFO": ("nse", DERIVATIVE_SEGMENTS),
        "BFO": ("bse", DERIVATIVE_SEGMENTS),
    }

    @staticmethod
    def identifier_parts(identifier):
        """
        Split a stored IND Money scrip code into its prefix and security id.

        Args:
            identifier (str): For example "NSE_2885".

        Returns:
            tuple: The prefix and the security id.
        """
        prefix, _, security_id = str(identifier).partition("_")
        return prefix, security_id

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of an IND Money scrip code.

        Args:
            identifier (str): For example "NSE_2885".

        Returns:
            SeriesContext: The security id, with the exchange and segments its prefix names.
        """
        prefix, security_id = cls.identifier_parts(identifier)
        exchange, family = cls.PREFIXES.get(prefix, (None, None))
        if family is None:
            return SeriesContext(security_id)
        return SeriesContext(security_id, exchange, segments_of(exchange, family),
                             exchange_token=security_id)

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of IND Money candles.

        The window goes out as epoch milliseconds. The response nests its bars under the scrip
        code they were asked about, so the code is looked up here and `parse_response` receives
        just that instrument's part.

        - `token` is the scrip code, such as `NSE_2885`.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        parameters = {"scrip-codes": token,
                      "start_time": str(self._epoch_milliseconds(start_date)),
                      "end_time": str(self._epoch_milliseconds(end_date
                                                               + datetime.timedelta(days=1)))}

        try:
            response = self._api.get(url=f"{HISTORICAL_URL}/{self.INTERVALS[interval]}",
                                     params=parameters)
        except Exception as exception:
            raise self._classify(exception) from exception

        # The API class unwraps the body's `data` field, which is the map of scrip code to bars.
        # A code with nothing in the window is sometimes present holding null and sometimes left
        # out altogether, so both are read as an empty window.
        return ((response or {}).get("data") or {}).get(token) or {}

    @staticmethod
    def _epoch_milliseconds(day):
        """
        Midnight India time on a date, as epoch milliseconds.

        - `day` is the date to convert.
        """
        moment = datetime.datetime(day.year, day.month, day.day, tzinfo=INDIA_TIMEZONE)
        return int(moment.timestamp() * 1000)

    @staticmethod
    def _classify(exception):
        """
        Decide what an IND Money refusal means for the series being downloaded.

        An unknown scrip code is an HTTP 400 naming "Invalid scrip codes", which retires the
        series. A throttle is a 429 carrying "Rate limit exceeded".

        - `exception` is what the API call raised.
        """
        text = str(exception)
        lowered = text.lower()

        if "invalid scrip" in lowered:
            return CandleInstrumentUnknown(text[:200])
        if "rate limit" in lowered or "429" in text:
            return CandleThrottled(text[:200])
        if "access_token" in lowered or "unauthor" in lowered or "401" in text:
            return CandleAuthenticationError(text[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn IND Money's candle list into bars.

        Each bar is an object keyed by initials, `ts` holding epoch seconds. There is no open
        interest on any interval, so that column is left null rather than invented.

        - `payload` is this instrument's part of the response.
        - `interval` is the stored interval name.
        """
        bars = []
        for record in (payload or {}).get("candles") or []:
            bar_time = datetime.datetime.fromtimestamp(int(record["ts"]), datetime.timezone.utc)
            if not is_intraday(interval):
                # A day bar arrives at midnight UTC, which is the trading day read in India time.
                bar_time = daily_bar_time(bar_time)
            bars.append((bar_time, record.get("o"), record.get("h"), record.get("l"),
                         record.get("c"), record.get("v"), None))
        return bars
