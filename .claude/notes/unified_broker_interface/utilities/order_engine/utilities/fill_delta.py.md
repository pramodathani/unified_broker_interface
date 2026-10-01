# fill_delta.py

## Why the option is the plan's own instrument (2026-10-01)

Today's attached hedge takes the delta of the parent's instrument, and in the `attached_hedge` preset that is the entry. A plan's hedge order is a Then child on the hedge instrument, so it reads the option from `context.parent.instrument_id` rather than from the first plan's order. An entry that overrides its own `instrument_id` would therefore not be the option sized against; no preset does that.

## Why the size is unsigned and the side decides

A put's delta is negative, so its hedge is on the same side as the entry. The expander cannot tell a call from a put, since it never reads the catalogue, so the hedge's side is `against_delta`, which `OrderPart._sending_side` resolves through `is_call` at the time the order is sent, and `scaled` gives the size of the delta alone.

## Why `scaled` can give None

Today's type logs a warning and sends nothing when the option has expired or the hedge has no price, then tries again on the next fill. `OrderPart.start` and `set_target` leave the order's size as it was when `scaled` gives None, which is the same.

## The clock

`delta` reads `time.time()`, as today's type does, so the offline suite's frozen clock gives both the same years to expiry. `EXPIRES_AT` and `SECONDS_IN_A_YEAR` are copied from `attached_hedge.py` rather than shared, since that type goes at the switch-over.
