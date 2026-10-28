# Notes on `stock_brokers/instruments/historical/base.py`

## `BIGINT_MINIMUM`, `BIGINT_MAXIMUM` and `BrokerCandles._value_within_bigint`

The `volume` and `oi` columns of every `<broker>.price_history` table are PostgreSQL `BIGINT`, which holds values from −2⁶³ to 2⁶³ − 1. The two constants are those limits.

On 2026-09-14 the Zerodha candle worker was found failing on 77 series across 49 small NSE equities. Kite's historical candles for 2023 carried volumes such as `18446744073709449716`, which is −101,900 written as an unsigned 64-bit integer, and one bar carried `9223372036854775908`, which is 2⁶³ + 100. BLUECHIP-BE (instrument token 2214401) had five such bars in its 60 minute window from 2023-06-03 to 2024-07-05. Postgres refused the whole insert with `bigint out of range`, `_store` rolled the window back, and because the next attempt asks for the same window, the backward walk could never get past it.

`_value_within_bigint` is called for the volume and the open interest of every bar in `_store`. A number inside the range is returned unchanged. A number outside it is replaced by `None`, which is stored as `NULL`, and a warning names the instrument, interval, bar time, column and the value as received, so the original value is still recoverable from the journal. Anything that is not an `int` or `float` is passed through untouched, because the parsers already convert their counts to numbers and the check should not change behaviour for any other type.

This is a deliberate exception to the project rule that data is stored exactly as the broker sent it. Three options were weighed:

| Option | Why it was or was not chosen |
| --- | --- |
| Store `NULL` and warn | Chosen. It keeps the bar and its prices, and an impossible count is no less informative as `NULL`. |
| Reinterpret the value as a signed integer | Rejected. It corrects the broker's data, and a negative volume would flow into `unified.price_history`. |
| Widen the columns to `NUMERIC(20,0)` | Rejected. 263 of the 265 chunks of `zerodha.price_history` (25 GB) are compressed, TimescaleDB cannot change a column type on compressed chunks, and `unified.price_history` would need the same change. |

The check lives in the base class rather than in `ZerodhaCandles.parse_response` because the limit belongs to the table, which every broker's table shares, not to Zerodha's response format.

The issue is also recorded in `docs/contributing/known-issues.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/known-issues.md`) and `docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`).

## Why candle requests time out after 30 seconds

On 2026-10-27 three candle downloads had been silent for days while systemd showed them running: Shoonya since 2026-10-23 19:33, Wisdom Capital since 2026-10-23 16:14 and Fyers since 2026-10-25 14:05. Each process held one open HTTPS connection to its broker and nothing else. None of the six request sites (`dhan.py`, `fyers.py`, `indmoney.py`, `noren.py` for Flattrade and Shoonya, `wisdom_capital.py`, `zerodha.py`) passed a timeout, so `requests` waited forever for an answer that never came.

They now pass `REQUEST_TIMEOUT_SECONDS` (30), longer than the 10 seconds used for logins because a candle answer can be large. A `requests.exceptions.ReadTimeout` was run through every broker's `_classify` on 2026-10-27 and each passed it through unchanged, so it reaches the generic `except` in `_fetch_and_store` and is recorded as one failed window rather than a login error or a block.

## Why a series set aside waits until midnight IST

`_defer_until_tomorrow` sets `next_attempt_after` to the next midnight in India time. Until 2026-10-28 it was `date_trunc('day', now()) + interval '1 day'`, which the database works out in its own time zone, UTC, so every up-to-date series woke at 05:30 IST. Each downloader then needs most of a day to get through its queue at its broker's rate limit: on 2026-10-28 Zerodha's daily series were refreshed between 06:00 and 21:00 IST and Flattrade's between 06:00 and 20:00, with Flattrade also paused from 09:00 to 15:45 by its own timer. The same day the unified price job moved to 02:00 IST, so the earlier the downloaders start, the more of the previous day's bars that job finds.

Midnight IST is also the day boundary the rest of the queue already uses: `next_window` asks for windows up to `datetime.date.today()`, which is the machine's local date, India time. Waking at UTC midnight meant a series was set aside for five and a half hours of a new India day before anything fetched it.

The risk is broker maintenance. Some brokers' APIs may be down for a while after midnight, and a failed window backs a series off for one hour, then two, four and so on, so a long outage could push some series past the market open. That had not been measured when the change was made; if the downloaders' logs show failures clustered after midnight, a later wake, such as 01:00 IST, keeps most of the gain.
