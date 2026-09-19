"""
Dhan historical candle download.

Dhan is the one broker here that splits its candles across two endpoints: daily bars come from
`/v2/charts/historical` and everything intraday from `/v2/charts/intraday`, with differently
formatted dates. Both are POSTs carrying a JSON body, and both answer columnar - one parallel
array per field rather than a list of rows - so the response is transposed into bars here.

Three things were settled against the live API on 2026-09-12 rather than taken from the
documentation.

Dhan serves exactly five intraday resolutions: 1, 5, 15, 25 and 60 minutes. Asking for any other
number is not refused, it returns an empty array, so an unsupported interval looks exactly like a
market holiday. `INTERVALS` therefore lists only what Dhan actually serves.

An empty window and a window before the instrument's history begins are reported differently. A
valid instrument with nothing to show - a Saturday - answers 200 with empty arrays. A window that
predates the instrument's first bar answers 400 with `DH-907`, which reads like an error and is
not one; it is the same "there is nothing here" in different clothes, so it is parsed as an empty
window. Retiring a series on `DH-907` would kill RELIANCE the moment its backward walk stepped
past 2002.

Daily bars are capped by nothing: a single request for 1990 to today returns the instrument's
entire history. Intraday requests are refused beyond ninety days, with a message that says so.
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

DAILY_URL = "https://api.dhan.co/v2/charts/historical"

INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"

# Dhan's own name for each exchange and segment pair, keyed by the two columns its instrument
# master publishes. NSE commodity - segment M under NSE, some twenty four thousand option
# contracts - is deliberately absent: Dhan lists those instruments but its charting API has no
# segment name for them, so they cannot be asked about at all.
EXCHANGE_SEGMENTS = {
    ("NSE", "E"): "NSE_EQ",
    ("NSE", "I"): "IDX_I",
    ("NSE", "D"): "NSE_FNO",
    ("NSE", "C"): "NSE_CURRENCY",
    ("BSE", "E"): "BSE_EQ",
    ("BSE", "I"): "IDX_I",
    ("BSE", "D"): "BSE_FNO",
    ("BSE", "C"): "BSE_CURRENCY",
    ("MCX", "M"): "MCX_COMM",
}

class DhanCandles(BrokerCandles):
    """
    Downloads Dhan's historical candles.
    """

    BROKER_NAME = "dhan"

    # Stored name to Dhan's own code. Only the five intraday resolutions Dhan actually serves are
    # here; the rest return an empty array rather than an error, which would be indistinguishable
    # from a holiday and would quietly retire every series asked for them.
    INTERVALS = {
        "1minute": "1",
        "5minute": "5",
        "15minute": "15",
        "25minute": "25",
        "60minute": "60",
        "day": "D",
    }

    # Measured: an intraday window wider than ninety days is refused with "Data for Intraday
    # Charts can be fetched for 90 days at a time", while a daily request for 1990 to today is
    # answered in full. The daily window is nevertheless finite, because the walk needs a step
    # size; fourteen years reaches Dhan's earliest date in two requests.
    MAXIMUM_WINDOW_DAYS = {
        "1minute": 90,
        "5minute": 90,
        "15minute": 90,
        "25minute": 90,
        "60minute": 90,
        "day": 5000,
    }

    # The DhanHQ v2 reference documents five a second and one hundred thousand a day for the data
    # APIs, and five a second is refused in practice: twenty five requests at that pace were
    # throttled four times, while the same twenty five at three a second passed cleanly. The
    # daily budget is what actually decides how long this backfill takes.
    REQUESTS_PER_SECOND = 3.0
    REQUESTS_PER_DAY = 100000

    EARLIEST_AVAILABLE_DATE = datetime.date(2000, 1, 1)

    TOKEN_COLUMN = "security_id"
    # `instrument` rather than `instrument_type`: they agree on this snapshot, and `instrument` is
    # the one the request body carries, so priority and the request read the same column.
    TYPE_COLUMN = "instrument"
    EXPIRY_COLUMN = "sm_expiry_date"

    def __init__(self, api=None):
        """
        Dhan candle downloader.

        - `api` is an authenticated `DhanAPI`. One is constructed when not supplied, which
          establishes a session if the stored one has expired.
        """
        super().__init__()
        if api is None:
            from stock_brokers.api.utilities.session import ensure_session
            from stock_brokers.api.dhan import DhanAPI

            # Through ensure_session rather than straight to DhanAPI, so this shares the Redis
            # lock and the login rate limiter with any other process using ensure_session. This
            # process runs for weeks and will be alive across an overnight token expiry, when
            # another process may be logging in too.
            ensure_session(self.BROKER_NAME, logger=self._logger)
            api = DhanAPI()
        self._api = api

    def instruments(self):
        """
        Every instrument Dhan has ever published, identified the way its charting API needs.

        Dhan's security id is not unique on its own: id 2885 is Reliance in the NSE cash segment
        and a 2025 EURINR option in the currency one, and the instrument master repeats ids this
        way some ten thousand times. So the identifier stored in the progress table is the
        security id, the exchange segment and the instrument name joined by bars, which is
        exactly the three fields the request body carries, and `fetch_candles` splits it again.

        Instruments in a segment Dhan does not chart are left out rather than registered and
        retired one request at a time.
        """
        query = f"""
            select distinct on (i.exch_id, i.segment, i."{self.TOKEN_COLUMN}")
                   i.exch_id, i.segment, i."{self.TOKEN_COLUMN}",
                   i."{self.TYPE_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
            order by i.exch_id, i.segment, i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        self._connection.commit()

        instruments = []
        for exchange, segment, token, instrument_type, expiry in rows:
            exchange_segment = EXCHANGE_SEGMENTS.get((exchange, segment))
            if exchange_segment is None or not instrument_type:
                continue
            instruments.append((f"{token}|{exchange_segment}|{instrument_type}",
                                instrument_type, expiry))
        return instruments

    # Dhan's exchange segment names, as they appear in the stored identifier.
    EXCHANGE_SEGMENTS = {
        "NSE_EQ": ("nse", CASH_SEGMENTS),
        "BSE_EQ": ("bse", CASH_SEGMENTS),
        "IDX_I": (None, INDEX_SEGMENTS),
        "NSE_FNO": ("nse", DERIVATIVE_SEGMENTS),
        "BSE_FNO": ("bse", DERIVATIVE_SEGMENTS),
        "NSE_CURRENCY": ("nse", DERIVATIVE_SEGMENTS),
        "BSE_CURRENCY": ("bse", DERIVATIVE_SEGMENTS),
        "MCX_COMM": ("mcx", DERIVATIVE_SEGMENTS),
    }

    @staticmethod
    def identifier_parts(identifier):
        """
        Split a stored Dhan identifier into the fields a request needs.

        The identifier is built in `instruments` and taken apart here and nowhere else, so the two
        cannot drift apart.

        Args:
            identifier (str): For example "2885|NSE_EQ|EQUITY".

        Returns:
            tuple: The security id, the exchange segment and the instrument type.
        """
        security_id, exchange_segment, instrument_type = str(identifier).split("|")
        return security_id, exchange_segment, instrument_type

    @classmethod
    def series_context(cls, identifier):
        """
        Read the exchange and segment out of a Dhan identifier.

        Args:
            identifier (str): For example "2885|NSE_EQ|EQUITY".

        Returns:
            SeriesContext: The security id, with the exchange and segments its segment names.
        """
        security_id, exchange_segment, _ = cls.identifier_parts(identifier)
        exchange, family = cls.EXCHANGE_SEGMENTS.get(exchange_segment, (None, None))
        if family is None:
            return SeriesContext(security_id)
        if exchange is None:
            return SeriesContext(security_id, None, segments_of(["nse", "bse"], family))
        return SeriesContext(security_id, exchange, segments_of([exchange], family),
                             exchange_token=security_id)

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of Dhan candles.

        The two endpoints take the same body but differently formatted dates, the intraday one
        wanting a time of day as well, which is why they are built separately.

        - `token` is the `securityId|exchangeSegment|instrument` identifier from `instruments`.
        - `interval` is the stored interval name.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        security_id, exchange_segment, instrument_type = self.identifier_parts(token)
        body = {"securityId": security_id, "exchangeSegment": exchange_segment,
                "instrument": instrument_type, "oi": True}

        if is_intraday(interval):
            url = INTRADAY_URL
            body["interval"] = self.INTERVALS[interval]
            body["fromDate"] = f"{start_date.isoformat()} 00:00:00"
            body["toDate"] = f"{end_date.isoformat()} 23:59:59"
        else:
            url = DAILY_URL
            body["fromDate"] = start_date.isoformat()
            body["toDate"] = end_date.isoformat()

        try:
            response = self._api.post(url=url, json=body)
        except Exception as exception:
            classified = self._classify(exception)
            if classified is None:
                # An empty window, dressed as an error. Answered with no bars rather than raised.
                return {}
            raise classified from exception

        return (response or {}).get("data") or {}

    @staticmethod
    def _classify(exception):
        """
        Decide what a Dhan refusal means for the series being downloaded.

        Dhan names its conditions in the body, and the API class turns that into an exception
        whose code is the error type and whose message is the error message. Returning None says
        the refusal is not a failure at all but an empty window.

        `DH-905`, Dhan's catch-all input error, is the one that retires a series: it is what an
        expired contract answers. It is also what a window wider than Dhan allows answers, and
        that would be a bug in this module rather than a dead instrument, so the message is read
        before the series is given up on.

        - `exception` is what the API call raised.
        """
        # The API class raises with Dhan's error type as the code and its message as the message,
        # and both end up in the exception's text. The numeric DH-9xx code does not, so the type
        # names are what is matched: Rate_Limit, Invalid_Authentication, Data_Error and the rest.
        text = str(exception)
        lowered = text.lower()

        if "rate_limit" in lowered or "too many requests" in lowered:
            return CandleThrottled(text[:200])
        if ("invalid_authentication" in lowered or "invalid_access" in lowered
                or "user_account" in lowered):
            return CandleAuthenticationError(text[:200])
        if "data_error" in lowered or "no data present" in lowered:
            return None
        if "input_exception" in lowered:
            if "at a time" in lowered or "days" in lowered:
                # The window this module asked for is wider than Dhan allows. Retrying the same
                # window will not help, but retiring the instrument would be wrong: the fault is
                # in MAXIMUM_WINDOW_DAYS, so it is left to fail loudly and back off.
                return exception
            return CandleInstrumentUnknown(text[:200])
        return exception

    def parse_response(self, payload, interval):
        """
        Turn Dhan's columnar response into bars.

        Dhan answers with one array per field rather than one object per bar, so the arrays are
        transposed here. Open interest is absent for cash instruments rather than present and
        zero, so it is read defensively.

        Dhan's timestamps are epoch seconds, and its daily bars already land on midnight India
        time; they are normalised anyway, so every broker's day bar in this project is produced
        the same way.

        - `payload` is the `data` object from the response.
        - `interval` is the stored interval name.
        """
        payload = payload or {}
        times = payload.get("timestamp") or []
        opens = payload.get("open") or []
        highs = payload.get("high") or []
        lows = payload.get("low") or []
        closes = payload.get("close") or []
        volumes = payload.get("volume") or []
        open_interests = payload.get("open_interest") or []

        bars = []
        for index, stamp in enumerate(times):
            if index >= min(len(opens), len(highs), len(lows), len(closes), len(volumes)):
                break
            bar_time = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc)
            if not is_intraday(interval):
                bar_time = daily_bar_time(bar_time)
            open_interest = open_interests[index] if index < len(open_interests) else None
            bars.append((bar_time, opens[index], highs[index], lows[index], closes[index],
                         volumes[index], open_interest))
        return bars
