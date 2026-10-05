# exposure_hedge_part.py

## The hedge instrument is the part's instrument (2026-10-02)

Today's type trades `hedge_instrument_id`, whatever the body names, and remembers that instrument's tick size. The part writes `hedge_instrument_id` into its overrides as its own instrument, so `OrderContext` prices the hedge from that instrument's quote and the plan remembers its tick size through `instruments()`, with nothing special in `PlanOrder`.

## Watching, not trading a quantity

The part places nothing when it starts, so the plan answers `armed`, and its hedges come from `move` on each tick. It never ends on its own: a filled hedge leaves it watching, and it is done only once its join or the caller has stopped it and its hedges have finished. The positions are the account's, read through the placement as today, and the hedges in flight are the part's own legs that were not rejected or cancelled.

## Counting, freshness, lots and refusals (2026-10-05)

`hedges_in_flight` counts what a finished hedge filled, so a hedge cancelled after 200 of 500 counts 200; it used to drop out, and the next hedge sold 700 against a need of 500. `positions_trusted` measures nothing from a missing document, one whose `as_of` is more than 60 seconds old, the writer's own staleness limit, or one marking a broker `stale` or `unreadable`; a missing document used to count as a flat account and a nine-day-old one as current. A `missing` broker is not counted against it, because a broker never read would block every hedge. `hedge_price` gives nothing from a quote marked stale. The hedge is rounded down to whole lots of the hedge instrument; 300 against a lot of 500 was refused on every tick with a traceback.

A refused or rejected hedge stops the part through `stop_refused`, which records `leaves_open`, so the parent ends `failed` when anything traded and `rejected` otherwise. A rejected hedge used to be sent again on every tick, and a refused first hedge left the parent rejected while the part said working.

Not fixed: when the hedge instrument is also watched, a filled hedge is counted twice once the positions document catches up with it. A baseline of the hedge instrument's position at the first tick fixed that but stopped the part seeing new trades in that instrument, which is the type's main use, and the document gives no reliable sign of whether it already holds a fill, so the choice is left to the user.
