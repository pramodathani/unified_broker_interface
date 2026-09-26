# Notes on `unified_broker_interface/utilities/instrument_history.py`

## Why the tick reader is split into three functions

`tick_stream` used to do everything for one `GET /ticks`: it checked the period, worked out the price basis, built the response headers and returned the row generator. A `POST /ticks` batch needs the same description of each instrument's series, but it puts that description inside each result entry rather than in headers, because headers can describe only one instrument.

The work is therefore split three ways:

- `check_tick_period` refuses a period that ends before it starts. The batch calls it once, before resolving anything, so a bad period is one 400 for the whole request.
- `tick_series` describes one instrument's series: its id, whether it is adjustable, its price basis, and the period.
- `tick_documents` is the row generator.

`tick_stream` builds its headers from `tick_series` and returns `tick_documents`, so the single route's answer is unchanged. The recording in `test_runs/instrument_routes.py` pins its headers and rows.

`tick_documents` is a generator function, so the connection and its server-side cursor open only when the response starts to be sent, exactly as the inner `generate()` did before. A batch opens one connection per instrument, one after another, as the stream reaches that instrument's entry.

## Why candles are not batched

`candles` is still called once per instrument. Its Redis copy is read in one round trip per series, and a copy that misses is read through `adjusted_bars()`, a set-returning function that takes one instrument. Batching the misses would need a `LATERAL` join over that function, for a path the Redis copy already makes rare.
