# Notes on `unified_broker_interface/utilities/order_engine/closing_price.py`

## Why it is a `Vwap` and not a `Twap`

The Atlas suggests either an even (E5) or a volume-weighted (E6) slicer through 15:00 to 15:30. The closing price is itself a volume-weighted average of that half hour, so weighting the slices by volume tracks the benchmark more closely than an even split. `Vwap`'s default profile gives the two buckets in that window weights of 0.093 and 0.143, so a six-slice order of 60 sends 8, 8, 8, 12, 12 and 12.

## How the scheduled start reuses `Twap`'s clock

`Twap.on_clock_tick` sends slice number `n` once the clock passes `started_at + interval × n`. Setting `started_at` to the window's start, and placing nothing in `run`, makes the first slice due at the window's start with no new scheduling code. `Twap.run` is what normally marks the parent `working`, so `on_clock_tick` here does that when the first scheduled slice goes out.

## Why `over_minutes` is refused

The window decides how long the order runs. Accepting `over_minutes` and ignoring it would let a caller believe they had asked for something else.
