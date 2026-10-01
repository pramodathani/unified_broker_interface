# exposure_hedge_part.py

## The hedge instrument is the part's instrument (2026-10-02)

Today's type trades `hedge_instrument_id`, whatever the body names, and remembers that instrument's tick size. The part writes `hedge_instrument_id` into its overrides as its own instrument, so `OrderContext` prices the hedge from that instrument's quote and the plan remembers its tick size through `instruments()`, with nothing special in `PlanOrder`.

## Watching, not trading a quantity

The part places nothing when it starts, so the plan answers `armed`, and its hedges come from `move` on each tick. It never ends on its own: a filled hedge leaves it watching, and it is done only once its join or the caller has stopped it and its hedges have finished. The positions are the account's, read through the placement as today, and the hedges in flight are the part's own legs that were not rejected or cancelled.
