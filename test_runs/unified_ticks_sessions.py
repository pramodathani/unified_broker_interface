"""
Offline test for the session gate against the exchanges' 2026 trading calendars.

Loads `stock_brokers/instruments/ticks/utilities/calendars/2026.yaml` - generated from each exchange's
own publication - and checks the gate against dates those publications state: a full equity holiday,
a commodity holiday that closes only the morning or only the evening, a currency-only bank holiday,
NCDEX's shorter evening, the Diwali Muhurat session, and ordinary weekdays and weekends. Needs no
Redis, no database and no broker:

    python -m test_runs.unified_ticks_sessions
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from stock_brokers.instruments.ticks.utilities.sessions import (COMMODITY_SESSION, CURRENCY_SESSION, EQUITY_SESSION,
                                                                NCDEX_SESSION, SessionGate, TradingCalendar,
                                                                session_for)

INDIA = ZoneInfo("Asia/Kolkata")

def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=INDIA).timestamp()

def check(description, actual, expected):
    status = "PASS" if actual == expected else "FAIL"
    print(f"[{status}] {description}: got {actual!r}, expected {expected!r}")
    return status == "PASS"

def main():
    r = []
    calendar = TradingCalendar.load()
    gate = SessionGate(calendar)
    weekday_count = lambda exchange, name: sum(1 for day in calendar.closures[(exchange, name)] if day.weekday() < 5)

    # --- the file matches the publications it was generated from --------------------------
    r.append(check("2026 is loaded", 2026 in calendar.years, True))
    r.append(check("weekday holidays per calendar, as published",
                   {key: weekday_count(*key) for key in sorted(calendar.closures)},
                   {("bse", "commodity"): 17, ("bse", "currency"): 20, ("bse", "equity"): 16, ("mcx", "commodity"): 16,
                    ("ncdex", "commodity"): 16, ("nse", "commodity"): 17, ("nse", "currency"): 20, ("nse", "equity"): 16}))
    for name in ("equity", "currency", "commodity"):
        nse = {day: kind for day, kind in calendar.closures[("nse", name)].items() if day.weekday() < 5}
        bse = {day: kind for day, kind in calendar.closures[("bse", name)].items() if day.weekday() < 5}
        r.append(check(f"NSE and BSE {name} calendars agree", nse, bse))

    # --- which session a segment follows --------------------------------------------------------
    r.append(check("NSE equities follow the equity session", session_for("nse_equities"), EQUITY_SESSION))
    r.append(check("NSE index options follow the equity session", session_for("nse_equity_index_options"), EQUITY_SESSION))
    r.append(check("NSE currency futures follow the currency session", session_for("nse_currency_futures"), CURRENCY_SESSION))
    r.append(check("NSE commodity futures follow the commodity session, not equity hours",
                   session_for("nse_commodity_futures"), COMMODITY_SESSION))
    r.append(check("MCX follows the commodity session", session_for("mcx_commodity_options"), COMMODITY_SESSION))
    r.append(check("NCDEX follows its own session", session_for("ncdex_commodity_futures"), NCDEX_SESSION))

    # --- ordinary days --------------------------------------------------------------------------
    r.append(check("Tuesday 2026-09-15 equity 10:00 open", gate.in_window("nse", EQUITY_SESSION, at("2026-09-15T10:00")), True))
    r.append(check("Tuesday equity 16:30 after the window", gate.in_window("nse", EQUITY_SESSION, at("2026-09-15T16:30")), False))
    r.append(check("Tuesday MCX 23:40 open", gate.in_window("mcx", COMMODITY_SESSION, at("2026-09-15T23:40")), True))
    r.append(check("Tuesday NSE commodity 22:00 open", gate.in_window("nse", COMMODITY_SESSION, at("2026-09-15T22:00")), True))
    r.append(check("Sunday 2026-09-13 closed", gate.in_window("nse", EQUITY_SESSION, at("2026-09-13T10:00")), False))
    r.append(check("Saturday mock session closed", gate.in_window("mcx", COMMODITY_SESSION, at("2026-09-12T21:00")), False))

    # --- Ganesh Chaturthi, Monday 2026-09-14: equity closed, commodity evening open ------------
    r.append(check("Ganesh Chaturthi NSE equity closed", gate.in_window("nse", EQUITY_SESSION, at("2026-09-14T10:00")), False))
    r.append(check("Ganesh Chaturthi BSE equity closed", gate.in_window("bse", EQUITY_SESSION, at("2026-09-14T10:00")), False))
    r.append(check("Ganesh Chaturthi NSE currency closed", gate.in_window("nse", CURRENCY_SESSION, at("2026-09-14T10:00")), False))
    r.append(check("Ganesh Chaturthi MCX morning closed", gate.in_window("mcx", COMMODITY_SESSION, at("2026-09-14T10:00")), False))
    r.append(check("Ganesh Chaturthi MCX evening open", gate.in_window("mcx", COMMODITY_SESSION, at("2026-09-14T18:00")), True))
    r.append(check("Ganesh Chaturthi NCDEX closed all day", gate.in_window("ncdex", NCDEX_SESSION, at("2026-09-14T18:00")), False))

    # --- New Year's Day: commodity morning open, evening closed ----------------------------------
    r.append(check("New Year MCX morning open", gate.in_window("mcx", COMMODITY_SESSION, at("2026-01-01T11:00")), True))
    r.append(check("New Year MCX closing prices kept until 17:30", gate.in_window("mcx", COMMODITY_SESSION, at("2026-01-01T17:20")), True))
    r.append(check("New Year MCX evening closed", gate.in_window("mcx", COMMODITY_SESSION, at("2026-01-01T19:00")), False))
    r.append(check("New Year NSE equity open", gate.in_window("nse", EQUITY_SESSION, at("2026-01-01T11:00")), True))

    # --- a bank holiday: currency closed, equity open ---------------------------------------------
    r.append(check("Id-E-Milad 2026-08-26 NSE currency closed", gate.in_window("nse", CURRENCY_SESSION, at("2026-08-26T11:00")), False))
    r.append(check("Id-E-Milad 2026-08-26 NSE equity open", gate.in_window("nse", EQUITY_SESSION, at("2026-08-26T11:00")), True))
    r.append(check("Annual Bank Closing 2026-04-01 BSE currency closed", gate.in_window("bse", CURRENCY_SESSION, at("2026-04-01T11:00")), False))

    # --- an exchange that does not list a holiday the others do ------------------------------------
    r.append(check("2026-01-15 NSE commodity morning closed", gate.in_window("nse", COMMODITY_SESSION, at("2026-01-15T11:00")), False))
    r.append(check("2026-01-15 MCX morning open, as MCX lists no holiday", gate.in_window("mcx", COMMODITY_SESSION, at("2026-01-15T11:00")), True))

    # --- NCDEX's evening ends at 21:00 ----------------------------------------------------------------
    r.append(check("NCDEX 20:59 open", gate.in_window("ncdex", NCDEX_SESSION, at("2026-09-15T20:59")), True))
    r.append(check("NCDEX 22:00 closed", gate.in_window("ncdex", NCDEX_SESSION, at("2026-09-15T22:00")), False))

    # --- Muhurat trading, Sunday 2026-11-08 --------------------------------------------------------------
    r.append(check("Muhurat Sunday NSE equity open", gate.in_window("nse", EQUITY_SESSION, at("2026-11-08T18:15")), True))
    r.append(check("Muhurat Sunday MCX open", gate.in_window("mcx", COMMODITY_SESSION, at("2026-11-08T18:15")), True))
    r.append(check("the Sunday after is closed", gate.in_window("nse", EQUITY_SESSION, at("2026-11-15T18:15")), False))

    # --- a window's end, for ownership spans --------------------------------------------------------------
    r.append(check("MCX span on New Year ends at 17:30", gate.window_end_epoch("mcx", COMMODITY_SESSION, at("2026-01-01T11:00")),
                   at("2026-01-01T17:30")))
    r.append(check("equity span ends at 16:00", gate.window_end_epoch("nse", EQUITY_SESSION, at("2026-09-15T11:00")),
                   at("2026-09-15T16:00")))

    # --- an empty calendar is every weekday open -----------------------------------------------------------
    empty = SessionGate(TradingCalendar.empty())
    r.append(check("empty calendar: Ganesh Chaturthi equity open", empty.in_window("nse", EQUITY_SESSION, at("2026-09-14T10:00")), True))
    r.append(check("empty calendar: weekends still closed", empty.in_window("nse", EQUITY_SESSION, at("2026-09-13T10:00")), False))

    passed = sum(r)
    print(f"\n{passed}/{len(r)} checks passed")
    raise SystemExit(0 if passed == len(r) else 1)

if __name__ == "__main__":
    main()
