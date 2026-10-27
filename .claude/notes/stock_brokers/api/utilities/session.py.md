# stock_brokers/api/utilities/session.py

## Why every long-running script now calls ensure_session

Until 2026-10-27 the 79 long-running scripts under `bin/<broker>/` built their broker class (or socket session, which builds the broker class) directly. A dead token made each of them run the full login on its own, fail, exit 1, and be restarted by `Restart=always` 15 seconds later. Nothing was shared between them, so a broker with seven services made seven independent login loops.

On 2026-10-27 the seven Flattrade services had each restarted about 2,046 times since midnight, roughly 14,000 logins, and Flattrade answered with `INVALID_SESSION` and once with no token at all. `groww-orders@websocket_order_details` asked Groww for a token 2,109 times, and Groww refused even after 38 quiet minutes, which suggests a daily cap on token generation rather than a short window.

Each script now calls `ensure_session("<broker>", logger=...)` as the first line of the `try` around its start-up login. The lock makes one process log in while the rest wait for its result, and the attempt key stops a failed login being retried sooner than `MIN_LOGIN_INTERVAL_SECONDS` (300) for that broker, however many services restart. The worst case is now about 12 login attempts an hour per broker instead of about 240 per service.

On the healthy path the cost is one extra probe: `ensure_session` builds the broker class to confirm the session when the last confirmation is older than the interval, and the script then builds its own.

## Where the import goes

The import is placed next to the script's first `stock_brokers` import. In six Fyers scripts, five Kotak scripts and `bin/indmoney/instruments/daily_feed` that first import sits inside a helper function (`start_session`, `kotak_request`, `downloader`), where it would not be visible in `main`; a `NameError` there would be caught by the login `except` and the script would fail every start. In those twelve the import sits directly above the `try` in `main` instead.

## What was checked

Every edited script was parsed and its import confirmed to be in module scope or the same function as the call. `python -m test_runs.websocket_feeds` matched all 160 recorded scenarios. No script was run against a live broker.
