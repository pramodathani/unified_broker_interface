"""
Offline test for the seven historical candle parsers.

Every broker answers a candle request in a shape of its own - a list of lists, one array per
field, a list of JSON encoded strings, one string holding everything - and each one has at least
one detail that is silently wrong if it is read the obvious way. This suite pins those details
down against payloads recorded from the live APIs on 2026-09-12, so a change to a parser that
breaks one of them fails here rather than three weeks into a backfill.

    python -m test_runs.candle_parse
"""

import json
import datetime
import zoneinfo

from stock_brokers.instruments.historical.base import daily_bar_time, is_intraday
from stock_brokers.instruments.historical.dhan import DhanCandles
from stock_brokers.instruments.historical.flattrade import FlattradeCandles
from stock_brokers.instruments.historical.fyers import FyersCandles
from stock_brokers.instruments.historical.indmoney import IndMoneyCandles
from stock_brokers.instruments.historical.noren import NorenCandles
from stock_brokers.instruments.historical.shoonya import ShoonyaCandles
from stock_brokers.instruments.historical.wisdom_capital import WisdomCapitalCandles
from stock_brokers.instruments.historical.zerodha import ZerodhaCandles

INDIA = zoneinfo.ZoneInfo("Asia/Kolkata")

def parser(cls):
    """
    A downloader with no Postgres, Mongo or broker session behind it.

    `parse_response` needs nothing but the class's own tables, so the object is made without
    running `__init__`, which would open a database connection and log the broker in.

    - `cls` is the downloader class to build.
    """
    return object.__new__(cls)

def check(description, actual, expected):
    """
    Print one check and say whether it passed.

    - `description` is what is being checked.
    - `actual` is what the parser produced.
    - `expected` is what it should have produced.
    """
    ok = actual == expected
    print(f"[{'PASS' if ok else 'FAIL'}] {description}: got {actual!r}, expected {expected!r}")
    return ok

def india(year, month, day, hour=0, minute=0, second=0):
    """
    A moment in India time, which is what every stored bar time should equal.

    - `year`, `month`, `day`, `hour`, `minute`, `second` name the moment.
    """
    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=INDIA)

def main():
    """Run every candle parser check."""
    r = []

    # --- the shared helpers ---------------------------------------------------------------
    r.append(check("minute names are intraday", [is_intraday(n) for n in
                                                 ("1minute", "240minute", "day", "week")],
                   [True, True, False, False]))
    r.append(check("a day bar at midnight UTC belongs to that date in India",
                   daily_bar_time(datetime.datetime(2026, 8, 3, tzinfo=datetime.timezone.utc)),
                   india(2026, 8, 3)))
    r.append(check("a day bar at 18:30 UTC belongs to the next date in India",
                   daily_bar_time(datetime.datetime(2026, 8, 2, 18, 30,
                                                    tzinfo=datetime.timezone.utc)),
                   india(2026, 8, 3)))
    try:
        daily_bar_time(datetime.datetime(2026, 8, 3))
        normalised_naive = "no error"
    except ValueError:
        normalised_naive = "refused"
    r.append(check("a naive bar time cannot be normalised", normalised_naive, "refused"))

    # --- Zerodha: a list of lists, six elements or seven -----------------------------------
    zerodha = parser(ZerodhaCandles)
    payload = {"candles": [["2026-09-11T09:15:00+0530", 1267.0, 1267.4, 1261.5, 1264.0, 375152],
                           ["2026-09-11T09:20:00+0530", 1264.0, 1264.5, 1262.6, 1263.3, 122562]]}
    bars = zerodha.parse_response(payload, "5minute")
    r.append(check("zerodha reads a cash candle", (bars[0][0], bars[0][1], bars[0][5], bars[0][6]),
                   (india(2026, 9, 11, 9, 15), 1267.0, 375152, None)))
    derivative = {"candles": [["2026-09-11T09:15:00+0530", 1285.0, 1291.0, 1283.6, 1290.5,
                               225000, 128846500]]}
    r.append(check("zerodha reads open interest from the seventh element",
                   zerodha.parse_response(derivative, "5minute")[0][6], 128846500))
    r.append(check("zerodha collapses a day bar onto its trading date",
                   zerodha.parse_response(
                       {"candles": [["2026-09-11T00:00:00+0530", 1, 2, 3, 4, 5]]}, "day")[0][0],
                   india(2026, 9, 11)))
    r.append(check("zerodha skips a short candle",
                   zerodha.parse_response({"candles": [[1, 2, 3]]}, "day"), []))
    r.append(check("zerodha reads an empty response", zerodha.parse_response({}, "day"), []))

    # --- Dhan: one array per field, transposed --------------------------------------------
    dhan = parser(DhanCandles)
    columnar = {"timestamp": [1788839100.0, 1788839400.0],
                "open": [1306.8, 1303.1], "high": [1306.8, 1304.0], "low": [1300.0, 1301.0],
                "close": [1303.1, 1302.0], "volume": [174555.0, 98434.0],
                "open_interest": [0.0, 0.0]}
    bars = dhan.parse_response(columnar, "5minute")
    r.append(check("dhan transposes its arrays into bars", len(bars), 2))
    r.append(check("dhan reads the first bar",
                   (bars[0][0], bars[0][1], bars[0][4], bars[0][5]),
                   (india(2026, 9, 8, 9, 15), 1306.8, 1303.1, 174555.0)))
    r.append(check("dhan collapses a day bar onto its trading date",
                   dhan.parse_response({"timestamp": [1009823400.0], "open": [55.73],
                                        "high": [56.46], "low": [55.31], "close": [55.75],
                                        "volume": [688738.0]}, "day")[0][0],
                   india(2002, 1, 1)))
    r.append(check("dhan leaves open interest null when the array is absent",
                   dhan.parse_response({"timestamp": [1788839100.0], "open": [1.0], "high": [2.0],
                                        "low": [0.5], "close": [1.5], "volume": [10.0]},
                                       "5minute")[0][6], None))
    r.append(check("dhan stops at the shortest array",
                   len(dhan.parse_response({"timestamp": [1.0, 2.0, 3.0], "open": [1.0],
                                            "high": [2.0], "low": [0.5], "close": [1.5],
                                            "volume": [10.0]}, "5minute")), 1))
    r.append(check("dhan reads an empty window", dhan.parse_response({}, "day"), []))

    # --- Dhan's refusals are classified, and one of them is not a refusal at all -----------
    r.append(check("dhan retires an instrument on Input_Exception",
                   type(DhanCandles._classify(
                       Exception("('Input_Exception', 'Missing required fields')"))).__name__,
                   "CandleInstrumentUnknown"))
    r.append(check("dhan treats Data_Error as an empty window, not a dead instrument",
                   DhanCandles._classify(
                       Exception("('Data_Error', 'System is unable to fetch data')")), None))
    r.append(check("dhan does not retire on a window that was too wide",
                   type(DhanCandles._classify(Exception(
                       "('Input_Exception', 'Data for Intraday Charts can be fetched for 90 "
                       "days at a time')"))).__name__, "Exception"))
    r.append(check("dhan stops the broker on a bad token",
                   type(DhanCandles._classify(
                       Exception("('Invalid_Authentication', 'token is invalid')"))).__name__,
                   "CandleAuthenticationError"))

    # --- Fyers: no_data is an empty window, not an error ------------------------------------
    fyers = parser(FyersCandles)
    r.append(check("fyers reads no_data as an empty window",
                   fyers.parse_response({"s": "no_data", "candles": []}, "1minute"), []))
    bars = fyers.parse_response({"s": "ok", "candles": [[1788839100, 1306.8, 1306.8, 1300.0,
                                                        1303.1, 174555]]}, "5minute")
    r.append(check("fyers reads a cash candle", (bars[0][0], bars[0][5], bars[0][6]),
                   (india(2026, 9, 8, 9, 15), 174555, None)))
    r.append(check("fyers reads open interest from the seventh element",
                   fyers.parse_response({"s": "ok", "candles": [[1788839100, 1, 2, 0.5, 1.5, 10,
                                                                 128846500]]}, "5minute")[0][6],
                   128846500))
    r.append(check("fyers collapses a day bar stamped midnight UTC onto its trading date",
                   fyers.parse_response({"s": "ok", "candles": [[1785715200, 1, 2, 0.5, 1.5, 10]]},
                                        "day")[0][0], india(2026, 8, 3)))
    r.append(check("fyers retires an instrument on an invalid symbol",
                   type(FyersCandles._classify(
                       Exception("(-300, 'Invalid symbol provided')"))).__name__,
                   "CandleInstrumentUnknown"))
    r.append(check("fyers does not retire on its catch-all input error",
                   type(FyersCandles._classify(Exception(
                       "(-50, 'Date range cannot exceed 366 days')"))).__name__, "Exception"))

    # --- IND Money: bars nested under the scrip code, and no open interest ------------------
    indmoney = parser(IndMoneyCandles)
    bars = indmoney.parse_response({"candles": [{"ts": 1788839100, "o": 1306.8, "h": 1306.8,
                                                 "l": 1300.0, "c": 1303.1, "v": 174555}]},
                                   "5minute")
    r.append(check("indmoney reads a bar", (bars[0][0], bars[0][1], bars[0][5]),
                   (india(2026, 9, 8, 9, 15), 1306.8, 174555)))
    r.append(check("indmoney leaves open interest null, because it serves none",
                   bars[0][6], None))
    r.append(check("indmoney collapses a day bar onto its trading date",
                   indmoney.parse_response({"candles": [{"ts": 1785715200, "o": 1, "h": 2, "l": 0.5,
                                                         "c": 1.5, "v": 10}]}, "day")[0][0],
                   india(2026, 8, 3)))
    r.append(check("indmoney reads a scrip with nothing in the window",
                   indmoney.parse_response({}, "day"), []))
    r.append(check("indmoney prefixes an NSE derivative with NFO",
                   IndMoneyCandles._scrip_prefix("NSE", "D"), "NFO"))
    r.append(check("indmoney prefixes cash with its exchange",
                   (IndMoneyCandles._scrip_prefix("NSE", "E"),
                    IndMoneyCandles._scrip_prefix("BSE", "E")), ("NSE", "BSE")))
    r.append(check("indmoney leaves out BSE derivatives, which it will not chart",
                   IndMoneyCandles._scrip_prefix("BSE", "D"), None))
    r.append(check("indmoney reads its expiry format",
                   IndMoneyCandles._expiry_date("09/29/2026 14:00"), datetime.date(2026, 9, 29)))

    # --- Noren: two response shapes, and the volume trap ------------------------------------
    noren = parser(ShoonyaCandles)
    intraday = [{"stat": "Ok", "time": "11-09-2026 15:29:00", "ssboe": "1789120740",
                 "into": "1257.50", "inth": "1257.50", "intl": "1257.50", "intc": "1257.50",
                 "intv": "7938419", "v": "8776602", "oi": "0"},
                {"stat": "Ok", "time": "11-09-2026 09:15:00", "ssboe": "1789098300",
                 "into": "1266.40", "inth": "1267.40", "intl": "1261.50", "intc": "1262.70",
                 "intv": "188567", "v": "188567", "oi": "0"}]
    bars = noren.parse_response(intraday, "1minute")
    r.append(check("noren sorts its bars oldest first",
                   [bar[0] for bar in bars],
                   [india(2026, 9, 11, 9, 15), india(2026, 9, 11, 15, 29)]))
    r.append(check("noren takes the bar's own volume, not the day's running total",
                   bars[0][5], 188567))
    r.append(check("noren reads the prices", (bars[1][1], bars[1][2], bars[1][3], bars[1][4]),
                   (1257.5, 1257.5, 1257.5, 1257.5)))
    eod = [json.dumps({"time": "11-SEP-2026", "into": "1267.00", "inth": "1267.40",
                       "intl": "1253.00", "intc": "1257.50", "ssboe": "1789084800",
                       "intv": "8777736.00"})]
    bars = noren.parse_response(eod, "day")
    r.append(check("noren decodes a daily bar out of its JSON string, onto its trading date",
                   (bars[0][0], bars[0][1], bars[0][5]),
                   (india(2026, 9, 11), 1267.0, 8777736)))
    r.append(check("noren reads a refusal as an empty window, because it cannot tell one from "
                   "an unknown instrument",
                   noren.parse_response({"stat": "Not_Ok",
                                         "emsg": 'Error Occurred : 5 "no data"'}, "1minute"), []))
    for description, message, expected in [
            ("a throttle", "Rate_Limited: too many requests", "CandleThrottled"),
            ("an expired session", "Session Expired", "CandleAuthenticationError")]:
        try:
            noren.parse_response({"stat": "Not_Ok", "emsg": message}, "1minute")
            raised = "nothing"
        except Exception as exception:
            raised = type(exception).__name__
        r.append(check(f"noren raises on {description}", raised, expected))
    r.append(check("noren reads its expiry format",
                   NorenCandles._expiry_date("27-OCT-2026"), datetime.date(2026, 10, 27)))
    r.append(check("the two Noren brokers differ only in host, rate and depth",
                   (FlattradeCandles.BASE_URL != ShoonyaCandles.BASE_URL,
                    FlattradeCandles.REQUESTS_PER_SECOND, ShoonyaCandles.REQUESTS_PER_SECOND),
                   (True, 10.0, 1.0)))

    # --- Wisdom Capital: one string, and a timestamp that needs two corrections -------------
    wisdom = parser(WisdomCapitalCandles)
    # The stamp is 09:15:59 read as though it were UTC: the last second of the one minute bar
    # that opened at 09:15 India time, which is exactly what the live one minute feed returned.
    bars = wisdom.parse_response("1789031759|1279.5|1285.3|1279.5|1283.2|149743|0|,"
                                 "1789031819|1283.2|1284.0|1282.0|1283.0|51743|0|", "1minute")
    r.append(check("wisdom capital splits its bar string", len(bars), 2))
    r.append(check("wisdom capital turns an end stamp read as UTC into an India time bar start",
                   bars[0][0], india(2026, 9, 10, 9, 15)))
    r.append(check("wisdom capital reads the bar",
                   (bars[0][1], bars[0][2], bars[0][3], bars[0][4], bars[0][5], bars[0][6]),
                   (1279.5, 1285.3, 1279.5, 1283.2, 149743, 0)))
    r.append(check("wisdom capital subtracts the bar's own length, so the same stamp read as a "
                   "five minute bar opens four minutes earlier",
                   wisdom.parse_response("1789031759|1|2|0.5|1.5|10|0|", "5minute")[0][0],
                   india(2026, 9, 10, 9, 11)))
    r.append(check("wisdom capital reads an empty window", wisdom.parse_response("", "5minute"),
                   []))
    r.append(check("wisdom capital skips a short bar",
                   wisdom.parse_response("1789031759|1|2|0.5", "5minute"), []))
    r.append(check("wisdom capital offers no daily interval, because its is a rolling bucket",
                   [name for name in WisdomCapitalCandles.INTERVALS if not is_intraday(name)], []))
    r.append(check("wisdom capital names its segments by number",
                   WisdomCapitalCandles.INTERVALS["1minute"], "60"))

    # --- every parser answers in the one shape the base class stores ------------------------
    for name, produced in [("zerodha", zerodha.parse_response(payload, "5minute")),
                           ("dhan", dhan.parse_response(columnar, "5minute")),
                           ("fyers", fyers.parse_response(
                               {"s": "ok", "candles": [[1788839100, 1, 2, 0.5, 1.5, 10]]},
                               "5minute")),
                           ("indmoney", indmoney.parse_response(
                               {"candles": [{"ts": 1788839100, "o": 1, "h": 2, "l": 0.5, "c": 1.5,
                                             "v": 10}]}, "5minute")),
                           ("noren", noren.parse_response(intraday, "1minute")),
                           ("wisdom_capital", wisdom.parse_response(
                               "1789031759|1|2|0.5|1.5|10|0|", "1minute"))]:
        r.append(check(f"{name} returns seven fields a bar",
                       {len(bar) for bar in produced}, {7}))
        r.append(check(f"{name} returns timezone aware bar times",
                       {bar[0].tzinfo is not None for bar in produced}, {True}))

    print()
    passed, total = sum(r), len(r)
    print(f"{passed}/{total} checks passed.")
    return 0 if passed == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
