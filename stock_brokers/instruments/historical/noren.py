"""
Shared machinery for the brokers running on the Noren platform: Flattrade and Shoonya.

The two speak the same protocol with the same field names and differ only in host, in rate limit
by a factor of ten, and in how much history they keep, so they share this class exactly as their
market feeds share one protocol. A subclass supplies the base URL, the API class,
the rate and how far back its deployment reaches.

Four things about the platform shape this module, all of them measured against both hosts on
2026-09-12.

**Two endpoints.** Intraday bars come from `TPSeries`, taking an exchange, a token and a
parameter spelled `intrv`; daily bars come from `EODChartData`, taking `EXCHANGE:TRADINGSYMBOL`.
That is why the progress table stores all three - exchange, token and trading symbol - joined
into one identifier.

**A refusal is not a failure.** A successful response is a JSON list; a refusal is a JSON object
carrying `stat` and `emsg`, and it arrives with HTTP 200. The message an empty window returns -
`Error Occurred : 5 "no data"` - is byte identical to the one an unknown token returns, so an
empty window cannot be told from a dead instrument by reading it. It is therefore treated as an
empty window always, and a series that is genuinely dead is retired by the base class when the
walk ends without a single bar rather than on the strength of this message.

**Two very different depths.** Intraday history is a rolling year, and the daily history is
several years - five on Shoonya, closer to seven on Flattrade. `EARLIEST_AVAILABLE_DATE` is the
daily one, because it is the deeper of the two; an intraday series simply walks past its own
depth, collects three empty windows and stops there.

**The year of intraday history has holes in it.** On both hosts, RELIANCE one minute bars are
missing for all of January to April 2026 while present either side. So the windows here are
deliberately wide - six months for one minute bars, a year for the rest - which crosses a gap of
that size inside a single window rather than mistaking it for the end of the history.

`EODChartData` answers with a list of JSON encoded strings rather than a list of objects, so each
element is decoded twice. `TPSeries` answers newest first. Both carry `ssboe`, the bar's epoch
seconds, which is read instead of the two differently formatted date strings beside it.
"""

import json
import re
import datetime

from stock_brokers.instruments.historical.base import (INDIA_TIMEZONE,
                                                       BrokerCandles,
                                                       CandleAuthenticationError,
                                                       CandleThrottled,
                                                       SeriesContext,
                                                       daily_bar_time,
                                                       is_intraday)
from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                             INDEX_SEGMENTS, segments_of)

class NorenCandles(BrokerCandles):
    """
    Downloads historical candles from a Noren deployment.

    A subclass sets `BROKER_NAME`, `BASE_URL`, `REQUESTS_PER_SECOND` and
    `EARLIEST_AVAILABLE_DATE`, and implements `_build_api`.
    """

    BASE_URL = None

    # Stored name to Noren's `intrv` value. The daily bar is served by a different endpoint
    # altogether rather than by an interval code, and "D" is kept here only so that every stored
    # interval has an entry.
    INTERVALS = {
        "1minute": "1",
        "2minute": "2",
        "3minute": "3",
        "5minute": "5",
        "10minute": "10",
        "15minute": "15",
        "30minute": "30",
        "60minute": "60",
        "120minute": "120",
        "240minute": "240",
        "day": "D",
    }

    # Noren caps nothing and truncates nothing: a single request for a year of one minute bars
    # returns all fifty eight thousand of them. These widths are chosen against the gaps in the
    # history rather than against a limit - wide enough that a missing quarter sits inside one
    # window instead of looking like the end of the data.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 180,
        "2minute": 365,
        "3minute": 365,
        "5minute": 365,
        "10minute": 365,
        "15minute": 365,
        "30minute": 365,
        "60minute": 365,
        "120minute": 365,
        "240minute": 365,
        "day": 4000,
    }

    REQUESTS_PER_DAY = None

    TOKEN_COLUMN = "token"
    TYPE_COLUMN = "instrument"
    EXPIRY_COLUMN = "expiry"

    def __init__(self, api=None):
        """
        Noren candle downloader.

        - `api` is an authenticated API class for this broker. One is built when not supplied,
          which establishes a session if the stored one has expired.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session

            # Through ensure_session, so this shares the Redis lock and the login rate limiter
            # with any other process using ensure_session. A backfill runs for weeks and will be
            # alive across a token expiry.
            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = self._build_api()
        self._api = api

    def _build_api(self):
        """
        Construct this broker's authenticated API class.
        """
        raise NotImplementedError

    def instruments(self):
        """
        Every instrument this deployment has published, identified for both endpoints.

        The two endpoints want different things - `TPSeries` an exchange and a numeric token,
        `EODChartData` an exchange joined to a trading symbol - so all three are stored as one
        identifier and split again when the request is built. One progress row then serves both.

        A Noren token is unique only within its scrip file: the same number appears under NSE and
        under NFO, some sixteen hundred times on this snapshot, which is why the exchange is part
        of the identifier rather than a detail recovered later.

        The expiry is converted from Noren's `27-OCT-2026` to a date, because `priority_for` reads
        dates and would otherwise queue every expired contract as though it were live.
        """
        query = f"""
            select distinct on (i.exchange, i."{self.TOKEN_COLUMN}")
                   i.exchange, i."{self.TOKEN_COLUMN}", i.tradingsymbol,
                   i."{self.TYPE_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
              and i.exchange is not null and i.exchange <> ''
              and i.tradingsymbol is not null and i.tradingsymbol <> ''
            order by i.exchange, i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        self._connection.commit()

        return [(f"{exchange}|{token}|{trading_symbol}", instrument_type,
                 self._expiry_date(expiry))
                for exchange, token, trading_symbol, instrument_type, expiry in rows]

    @staticmethod
    def _expiry_date(expiry):
        """
        Turn Noren's `27-OCT-2026` expiry into a date, or None when there is none.

        - `expiry` is the `expiry` column.
        """
        if not expiry:
            return None
        try:
            return datetime.datetime.strptime(str(expiry).strip(), "%d-%b-%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _epoch_seconds(day):
        """
        Midnight India time on a date, as epoch seconds, which is what Noren's windows take.

        - `day` is the date to convert.
        """
        return int(datetime.datetime(day.year, day.month, day.day,
                                     tzinfo=INDIA_TIMEZONE).timestamp())

    # Noren's exchange names. Its NSE and BSE files carry both cash scrips and indices under the
    # same exchange, so a series on either can be in any of those segments.
    EXCHANGES = {
        "NSE": ("nse", CASH_SEGMENTS + INDEX_SEGMENTS),
        "BSE": ("bse", CASH_SEGMENTS + INDEX_SEGMENTS),
        "NFO": ("nse", DERIVATIVE_SEGMENTS),
        "BFO": ("bse", DERIVATIVE_SEGMENTS),
        "CDS": ("nse", DERIVATIVE_SEGMENTS),
        "BCD": ("bse", DERIVATIVE_SEGMENTS),
        "MCX": ("mcx", DERIVATIVE_SEGMENTS),
        "NCX": ("ncdex", DERIVATIVE_SEGMENTS),
    }

    # The series an NSE cash trading symbol ends with: EQ, BE, BZ, SM, ST, GB and the like.
    SERIES_SUFFIX = re.compile(r"-[A-Z0-9]{2}$")

    @staticmethod
    def identifier_parts(identifier):
        """
        Split a stored Noren identifier into the fields the two endpoints need.

        The identifier is built in `instruments` and taken apart here and nowhere else, so the two
        cannot drift apart.

        Args:
            identifier (str): For example "NSE|2885|RELIANCE-EQ".

        Returns:
            tuple: The exchange, the numeric token and the trading symbol.
        """
        exchange, instrument_token, trading_symbol = str(identifier).split("|", 2)
        return exchange, instrument_token, trading_symbol

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of a Noren identifier.

        Args:
            identifier (str): For example "NSE|2885|RELIANCE-EQ".

        Returns:
            SeriesContext: The numeric token, with the exchange and segments its exchange names.
        """
        exchange_name, instrument_token, trading_symbol = cls.identifier_parts(identifier)
        exchange, family = cls.EXCHANGES.get(exchange_name, (None, None))
        if family is None:
            return SeriesContext(instrument_token)
        symbol = None
        if exchange_name in ("NSE", "BSE"):
            # An NSE cash symbol carries its series, as in RELIANCE-EQ or INDIAGLYCO-BE; BSE's do not.
            symbol = cls.SERIES_SUFFIX.sub("", trading_symbol)
        return SeriesContext(instrument_token, exchange, segments_of(exchange, family),
                             exchange_token=instrument_token, symbol=symbol)

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of Noren candles.

        The API class wraps the body into the `jData=...&jKey=...` form Noren expects and adds the
        user id, so only the fields particular to the request are named here.

        - `token` is the `EXCHANGE|token|tradingsymbol` identifier from `instruments`.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        exchange, instrument_token, trading_symbol = self.identifier_parts(token)
        # The window ends at midnight of the day after, so the last day's bars are inside it.
        start = self._epoch_seconds(start_date)
        end = self._epoch_seconds(end_date + datetime.timedelta(days=1))

        if is_intraday(interval):
            endpoint = "TPSeries"
            body = {"exch": exchange, "token": instrument_token, "st": str(start),
                    "et": str(end), "intrv": self.INTERVALS[interval]}
        else:
            endpoint = "EODChartData"
            body = {"sym": f"{exchange}:{trading_symbol}", "from": str(start), "to": str(end)}

        try:
            response = self._api.post(url=f"{self.BASE_URL}/{endpoint}", data=body)
        except Exception as exception:
            raise self._classify(exception) from exception

        return (response or {}).get("data")

    def _classify(self, exception):
        """
        Decide what a Noren refusal means for the series being downloaded.

        Nothing here retires a series. Noren reports an unknown instrument and an empty window
        with the same message, so the only safe reading of that message is "no bars", and a dead
        instrument is retired by the base class when its walk ends having collected none.

        - `exception` is what the API call raised.
        """
        text = str(exception)
        lowered = text.lower()

        if "rate_limited" in lowered or "too many requests" in lowered or "429" in text:
            return CandleThrottled(text[:200])
        if "session expired" in lowered or "invalid session key" in lowered:
            return CandleAuthenticationError(text[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn a Noren response into bars.

        A refusal object is answered with no bars rather than raised, for the reason in
        `_classify`: its message cannot tell an empty window from a dead instrument.

        `EODChartData` returns each bar as a JSON encoded string inside the list, so a string
        element is decoded before it is read. The volume taken is `intv`, the bar's own volume;
        the `v` beside it is the day's running total, and taking that by mistake would produce a
        rising series that looks plausible on a chart and is wrong everywhere.

        - `payload` is the decoded response, a list of bars or a refusal object.
        - `interval` is the stored interval name.
        """
        if isinstance(payload, dict):
            self._raise_for_refusal(payload)
            return []
        if not isinstance(payload, list):
            return []

        bars = []
        for element in payload:
            record = json.loads(element) if isinstance(element, str) else element
            if not isinstance(record, dict) or record.get("stat") == "Not_Ok":
                continue
            bar_time = datetime.datetime.fromtimestamp(int(record["ssboe"]),
                                                       datetime.timezone.utc)
            if not is_intraday(interval):
                bar_time = daily_bar_time(bar_time)
            open_interest = record.get("oi")
            bars.append((bar_time,
                         float(record["into"]), float(record["inth"]),
                         float(record["intl"]), float(record["intc"]),
                         int(float(record.get("intv") or 0)),
                         int(float(open_interest)) if open_interest is not None else None))
        bars.sort(key=lambda bar: bar[0])
        return bars

    def _raise_for_refusal(self, body):
        """
        Raise for the refusals that mean something other than an empty window.

        Noren answers HTTP 200 with an object when it refuses, so a throttle and an expired
        session arrive here rather than as exceptions from the API class.

        - `body` is the refusal object, carrying `stat` and `emsg`.
        """
        message = str(body.get("emsg", ""))
        lowered = message.lower()
        if "rate_limited" in lowered or "too many requests" in lowered:
            raise CandleThrottled(f"{self.BROKER_NAME} refused the request for rate: "
                                  f"{message[:150]}")
        if "session expired" in lowered or "invalid session key" in lowered:
            raise CandleAuthenticationError(f"{self.BROKER_NAME} rejected the session key: "
                                            f"{message[:150]}")
