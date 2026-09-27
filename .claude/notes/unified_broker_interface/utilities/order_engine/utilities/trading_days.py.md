# Notes on `unified_broker_interface/utilities/order_engine/utilities/trading_days.py`

## Why the order types read the tick pipeline's calendar

In the live test of 2026-09-27, a Sunday, the time-based types behaved as if every day traded: `scheduled` and `closing_price` were set to act at 15:00 that Sunday, `daily_stop` placed its stop at once because 09:20 had passed, and `opening_auction` refused with "stopped taking this order at 09:10 today" without naming Monday. The project already has an exact answer to "does this segment trade today", in `SessionGate`, which the tick pipeline built from each exchange's published holiday list, including half-closed commodity days and Muhurat trading, and which `test_runs.unified_ticks_sessions` checks. `TradingDays` is a thin reader over it rather than a second calendar. A day that only closes a commodity morning or evening still counts as trading, because part of it does.
