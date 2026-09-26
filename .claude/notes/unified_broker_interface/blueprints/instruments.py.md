# Notes on `unified_broker_interface/blueprints/instruments.py`

## One handler per route, two methods

`BaseBlueprint` registers one handler per URL rule, so each of the seven instrument routes lists both `GET` and `POST` and its handler starts with `if request.method == 'POST'`, passing a `POST` to a `_<route>_batch` method beside it. The `GET` bodies were left as they were, apart from `/prices`, whose parameter checks moved into `_price_request` so that both forms check `interval`, the date range, `adjusted` and `known_as_of` in the same way.

One consequence of that move is visible only for a request that is wrong in two ways at once. `GET /prices` now reads `adjusted` and `known_as_of` before looking up the instrument, where it used to read them after. A request with both a bad `adjusted` and an unknown instrument therefore answers 400 about `adjusted` instead of 404 about the instrument. Every singly wrong request answers exactly as before, which the recording in `test_runs/instrument_routes.py` pins.

## Why shared parameters are checked before anything is resolved

In `_prices_batch` and `_ticks_batch`, the range and period are checked once, up front, with `check_candle_range` and `check_tick_period`. A bad range applies to every instrument, so it is one 400 for the whole request rather than the same 400 repeated in every entry, and it costs no Redis reads.

## Why `/ticks` resolves everything before it streams

A streamed answer has already sent its 200 by the time the first row is written, so anything that should have its own status has to be known first. Every instrument is resolved before `json_results_response` starts, which gives an unknown instrument its own 404 entry. Only the tick queries run inside the stream, one per instrument, as the stream reaches each entry.
