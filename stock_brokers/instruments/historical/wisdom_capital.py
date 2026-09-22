"""
Wisdom Capital historical candle download.

Wisdom Capital runs Symphony's XTS platform, and four things about it are unlike every other
broker here. All four were measured on 2026-09-12 rather than taken from documentation.

**It needs a different session.** XTS splits a broker into two applications with separate
credentials, and the interactive token is refused by the chart endpoint, which lives under
`/apimarketdata`. `WisdomCapitalAPI` establishes both sessions when it is constructed and keeps
the market data one in `last_login` as `market_data_access_token`, so this module asks that class
for the token - the same one `bin/wisdom_capital/instruments/websocket_quotes` carries - and sends
it on every request.

**The bars are not JSON.** They arrive inside one string under a key the platform spells
`dataReponse`, comma separated between bars and pipe separated within one.

**Its timestamps need two corrections.** The number is seconds since the epoch computed as though
India time were UTC, so decoding it as UTC and relabelling the result as India time gives the
India wall clock reading directly. And it names the last second of the bar rather than the first,
so the bar's own length less one second is subtracted to reach its start. Both were checked
against Flattrade's one minute bars for the same session: the starts line up exactly.

**There is no daily interval.** A compression of 86,400 seconds returns a rolling twenty four
hour bucket running from 09:15 one day to 09:14:59 the next, not the exchange's session, which
was confirmed by asking for it. A bar like that would sit in `price_history` looking like a daily
bar and comparing against real ones, so it is not offered at all.

The fifth difference is the dangerous one. **An empty response says nothing.** An instrument the
platform does not recognise, a window before its history begins, and an expired market data token
all answer with the same envelope: a type of success and an empty `dataReponse`. So a run of
empty windows cannot be trusted here the way it can elsewhere - a token that expired mid-backfill
would look exactly like tens of thousands of dead instruments, and the base class would retire
every series it touched. That is what `_check_still_alive` is for: after a run of empty windows it
asks about an instrument known to have bars, and if that comes back empty too it logs in again
and asks once more before concluding the session is the problem and stopping the broker.
"""

import datetime

from stock_brokers.instruments.historical.base import (INDIA_TIMEZONE,
                                                       BrokerCandles,
                                                       CandleAuthenticationError,
                                                       CandleInstrumentUnknown,
                                                       CandleThrottled,
                                                       SeriesContext)
from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                             INDEX_SEGMENTS, segments_of)

HISTORICAL_URL = "https://trade.wisdomcapital.in/apimarketdata/instruments/ohlc"

# What the platform's own instrument files call a segment, and the number the wire wants.
EXCHANGE_SEGMENT_NUMBERS = {
    "NSECM": 1,
    "NSEFO": 2,
    "NSECD": 3,
    "NSECO": 4,
    "BSECM": 11,
    "BSEFO": 12,
    "BSECD": 13,
    "NCDEX": 21,
    "MCXFO": 51,
}

# XTS names an instrument's kind with a number. Only enough of them to order the queue: a future
# and an option are queued differently, and everything else is cash.
INSTRUMENT_TYPES = {
    "1": "FUT",
    "2": "OPT",
    "4": "SPREAD",
    "8": "EQ",
    "16": "COMBINATION",
}

# The instrument the session check asks about: NSE cash RELIANCE, which has bars on every trading
# day there has ever been one.
CANARY_SEGMENT = 1
CANARY_INSTRUMENT = 2885

# How many empty windows in a row before the session itself is suspected. Empty windows are
# normal - most expired contracts answer that way - so this is high enough that the check costs
# about one request in fifty, and low enough that a dead token is caught long before a day's work
# has been thrown away.
EMPTY_WINDOWS_BEFORE_CHECKING = 50

class WisdomCapitalCandles(BrokerCandles):
    """
    Downloads Wisdom Capital's historical candles.
    """

    BROKER_NAME = "wisdom_capital"

    # Stored name to the compression in seconds, which is what the request carries. There is no
    # daily entry: see the note at the top of this module.
    INTERVALS = {
        "1minute": "60",
        "2minute": "120",
        "3minute": "180",
        "5minute": "300",
        "10minute": "600",
        "15minute": "900",
        "20minute": "1200",
        "30minute": "1800",
        "45minute": "2700",
        "60minute": "3600",
        "120minute": "7200",
        "180minute": "10800",
        "240minute": "14400",
    }

    # The platform truncates nothing: a year of five minute bars came back whole. These widths
    # are a choice about response size rather than a limit - ninety days of one minute bars is
    # some twenty four thousand of them in a single string.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 90,
        "2minute": 180,
        "3minute": 180,
        "5minute": 365,
        "10minute": 365,
        "15minute": 365,
        "20minute": 365,
        "30minute": 365,
        "45minute": 365,
        "60minute": 365,
        "120minute": 365,
        "180minute": 365,
        "240minute": 365,
    }

    # Symphony documents no rate for this endpoint, so this is conservative rather than measured.
    REQUESTS_PER_SECOND = 1.0
    REQUESTS_PER_DAY = None

    # One minute bars answer for September 2022 and are empty for September 2020, so the history
    # begins between the two. The walk stops on empty windows either way.
    EARLIEST_AVAILABLE_DATE = datetime.date(2021, 1, 1)

    TOKEN_COLUMN = "exchangeinstrumentid"
    TYPE_COLUMN = "instrumenttype"
    EXPIRY_COLUMN = "contractexpiration"

    # The platform's own time format, read as India wall clock.
    TIME_FORMAT = "%b %d %Y %H%M%S"

    def __init__(self, api=None):
        """
        Wisdom Capital candle downloader.

        - `api` is an authenticated `WisdomCapitalAPI`. One is constructed when not supplied.
          Either way a market data session is established on top of it, because the chart
          endpoint does not accept the interactive token.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session
            from stock_brokers.api.wisdom_capital import WisdomCapitalAPI

            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = WisdomCapitalAPI()
        self._api = api
        self._market_data_token = None
        self._empty_streak = 0
        self._log_in_to_market_data()

    def _log_in_to_market_data(self, refresh=False):
        """
        Take the market data token the broker session holds, replacing it when it has been refused.

        Separate from the broker's ordinary session: XTS issues one token for trading and another
        for market data, and the chart endpoint refuses the first. `WisdomCapitalAPI` establishes
        both and publishes them in the shared `last_login`, so this asks that class for the token
        rather than minting one - a second market data login invalidates the first, which would
        take the live quotes feed's token with it.

        - `refresh` replaces the token in hand, for one that has stopped working. Rotating it is
          not destructive: whoever reads it next gets the new one.
        """
        try:
            session = self._api.replace_market_data_session(
                stale_access_token=self._market_data_token if refresh else None)
        except Exception as exception:
            raise CandleAuthenticationError(
                f"wisdom_capital market data login failed: "
                f"{type(exception).__name__}: {str(exception)[:200]}") from exception
        self._market_data_token = session["access_token"]

    def after_relogin(self):
        """
        Take the market data token again after the broker session has been logged in again.

        The chart endpoint takes the market data token, not the interactive one, so a fresh
        interactive session alone would leave a refused credential in place. Building the API
        class checks the market data token as well and replaces it only when it has stopped
        working, so this takes what that check settled on rather than forcing a new login, which
        would invalidate the token the live quotes feed is using. The empty-window check does
        force one, because there the market data token is what is suspect.
        """
        self._log_in_to_market_data()

    def instruments(self):
        """
        Every instrument Wisdom Capital has published, identified the way the wire needs.

        The identifier is the segment's number joined to the instrument id, because one
        instrument id appears under several segments and the request carries both. The segment
        number comes from the platform's own segment name rather than from anything translated,
        since the names map one to one onto the numbers.

        The instrument type is turned from XTS's number into a word so that `priority_for` can
        tell a future from an option, and the expiry is already ISO-8601 and needs nothing.
        """
        query = f"""
            select distinct on (i.exchangesegment, i."{self.TOKEN_COLUMN}")
                   i.exchangesegment, i."{self.TOKEN_COLUMN}",
                   i."{self.TYPE_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
            order by i.exchangesegment, i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        self._connection.commit()

        instruments = []
        for segment, token, instrument_type, expiry in rows:
            number = EXCHANGE_SEGMENT_NUMBERS.get(segment)
            if number is None:
                continue
            instruments.append((f"{number}|{token}",
                                INSTRUMENT_TYPES.get(str(instrument_type), instrument_type),
                                expiry))
        return instruments

    # XTS exchange segment numbers, as stored in the identifier.
    SEGMENT_NUMBERS = {
        "1": ("nse", CASH_SEGMENTS),
        "2": ("nse", DERIVATIVE_SEGMENTS),
        "3": ("nse", DERIVATIVE_SEGMENTS),
        "11": ("bse", CASH_SEGMENTS),
        "12": ("bse", DERIVATIVE_SEGMENTS),
        "13": ("bse", DERIVATIVE_SEGMENTS),
        "51": ("mcx", DERIVATIVE_SEGMENTS),
    }

    @staticmethod
    def identifier_parts(identifier):
        """
        Split a stored Wisdom Capital identifier into its segment number and instrument id.

        The identifier is built in `instruments` and taken apart here and nowhere else, so the two
        cannot drift apart.

        Args:
            identifier (str): For example "11|500325".

        Returns:
            tuple: The segment number and the exchange instrument id.
        """
        segment_number, instrument_identifier = str(identifier).split("|", 1)
        return segment_number, instrument_identifier

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of a Wisdom Capital identifier.

        Args:
            identifier (str): For example "11|500325".

        Returns:
            SeriesContext: The instrument id, with the exchange and segments its number names.
        """
        segment_number, instrument_identifier = cls.identifier_parts(identifier)
        exchange, family = cls.SEGMENT_NUMBERS.get(segment_number, (None, None))
        if family is None:
            return SeriesContext(instrument_identifier)
        return SeriesContext(instrument_identifier, exchange, segments_of(exchange, family),
                             exchange_token=instrument_identifier)

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of Wisdom Capital candles.

        - `token` is the `segmentNumber|instrumentId` identifier from `instruments`.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        segment_number, instrument_identifier = self.identifier_parts(token)
        window_start = datetime.datetime(start_date.year, start_date.month, start_date.day)
        window_end = datetime.datetime.combine(end_date + datetime.timedelta(days=1),
                                               datetime.time(0, 0))

        payload = self._ask(segment_number, instrument_identifier, self.INTERVALS[interval],
                            window_start, window_end)

        if payload:
            self._empty_streak = 0
        else:
            self._empty_streak += 1
            if self._empty_streak >= EMPTY_WINDOWS_BEFORE_CHECKING:
                self._check_still_alive()

        return payload

    def _ask(self, segment_number, instrument_identifier, compression, window_start, window_end):
        """
        Make one request and return the bar string it carried, which may be empty.

        - `segment_number` is the XTS exchange segment number.
        - `instrument_identifier` is the instrument id within that segment.
        - `compression` is the bar length in seconds.
        - `window_start` and `window_end` are India wall clock times bounding the window.
        """
        parameters = {"exchangeSegment": segment_number,
                      "exchangeInstrumentID": instrument_identifier,
                      "startTime": window_start.strftime(self.TIME_FORMAT),
                      "endTime": window_end.strftime(self.TIME_FORMAT),
                      "compressionValue": compression}

        try:
            response = self._api.get(url=HISTORICAL_URL,
                                     headers={"authorization": self._market_data_token},
                                     params=parameters)
        except Exception as exception:
            raise self._classify(exception) from exception

        # The API class unwraps the envelope's `result`, which is where the bars live. The
        # platform's spelling of the key is kept, and the correct spelling accepted too in case
        # that is ever fixed.
        result = (response or {}).get("data") or {}
        return result.get("dataReponse") or result.get("dataResponse") or ""

    def _check_still_alive(self):
        """
        Decide whether a run of empty windows means dead instruments or a dead session.

        This platform answers an unknown instrument, a window before the history begins and an
        expired market data token identically, so the only way to tell them apart is to ask about
        an instrument that is known to have bars. If that is empty too the token is logged in
        again and asked once more, because expiry is the likeliest explanation and it is cheap to
        fix. Only if the second answer is empty as well is the broker stopped.
        """
        self._empty_streak = 0
        yesterday = datetime.datetime.now(INDIA_TIMEZONE).replace(tzinfo=None)
        window_start = yesterday - datetime.timedelta(days=7)

        self._limiter.take()
        if self._ask(str(CANARY_SEGMENT), str(CANARY_INSTRUMENT), "3600",
                     window_start, yesterday):
            return

        self._logger.warning(f"{EMPTY_WINDOWS_BEFORE_CHECKING} empty windows in a row and the "
                             f"session check came back empty too. Logging in again.")
        self._log_in_to_market_data(refresh=True)

        self._limiter.take()
        if self._ask(str(CANARY_SEGMENT), str(CANARY_INSTRUMENT), "3600",
                     window_start, yesterday):
            return

        # This check has already logged the market data session in again, which is the one login
        # the rule allows. Marking it spent stops the base class logging in a second time.
        self._relogin_used = True
        raise CandleAuthenticationError(
            "wisdom_capital answers every window empty, including one for an instrument that "
            "always has bars, and a fresh market data login did not change it. Stopping rather "
            "than retiring series that may be perfectly good.")

    @staticmethod
    def _classify(exception):
        """
        Decide what a Wisdom Capital refusal means for the series being downloaded.

        The platform names its conditions in the body with codes of its own, which the API class
        raises as the exception's code.

        - `exception` is what the API call raised.
        """
        text = str(exception)
        lowered = text.lower()

        if "e-apirl" in lowered or "429" in text or ("rate" in lowered and "limit" in lowered):
            return CandleThrottled(text[:200])
        if "e-session" in lowered or "e-token" in lowered:
            return CandleAuthenticationError(text[:200])
        if "e-instrument" in lowered:
            return CandleInstrumentUnknown(text[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn Wisdom Capital's bar string into bars.

        Each bar is `timestamp|open|high|low|close|volume|openInterest`, bars separated by commas,
        with a trailing pipe leaving an empty last field.

        - `payload` is the bar string `fetch_candles` returned.
        - `interval` is the stored interval name. It is needed rather than ignored, because the
          timestamp names the end of the bar and the bar's own length is what converts that into
          its start.
        """
        bar_seconds = int(self.INTERVALS[interval])

        bars = []
        for row in (payload or "").split(","):
            if not row:
                continue
            fields = row.split("|")
            if len(fields) < 7:
                continue
            bars.append((self._bar_start_time(int(fields[0]), bar_seconds),
                         float(fields[1]), float(fields[2]), float(fields[3]), float(fields[4]),
                         int(float(fields[5])), int(float(fields[6]))))
        bars.sort(key=lambda bar: bar[0])
        return bars

    @staticmethod
    def _bar_start_time(stamp, bar_seconds):
        """
        Turn one of the platform's timestamps into the time the bar opened.

        Two corrections, both measured. The number is seconds since the epoch computed as though
        India time were UTC, so it is decoded as UTC and the result relabelled as India time,
        which yields the India wall clock reading directly. And it names the bar's last second,
        so the bar's length less one second is subtracted to reach its start.

        - `stamp` is the epoch value as the platform reported it.
        - `bar_seconds` is the length of the bar in seconds.
        """
        india_reading = datetime.datetime.fromtimestamp(
            stamp, datetime.timezone.utc).replace(tzinfo=INDIA_TIMEZONE)
        return india_reading - datetime.timedelta(seconds=bar_seconds - 1)
