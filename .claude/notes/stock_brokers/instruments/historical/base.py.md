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

The issue is also recorded in `docs/contributing/known-issues.md` and `docs/contributing/pitfalls.md`.
