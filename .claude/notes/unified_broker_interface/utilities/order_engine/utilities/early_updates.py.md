# Notes on `unified_broker_interface/utilities/order_engine/utilities/early_updates.py`

## Why this is its own class

The follower decides what an update means; this class only remembers updates for a while. Keeping the remembering apart means the follower's `follow` reads the same as before, with one line that hands an unknown update over instead of dropping it, and the holding rules (how long, how many, which to hand back) can be read in one short file.

## Why times are monotonic

A held update is compared with the holding time using `time.monotonic()`, not the wall clock, so a clock adjustment by NTP cannot make every held update look expired at once, or keep one held for ever.

## Why the cap drops the oldest

When more than 10,000 updates are held, the oldest go first. The oldest is the least likely to be one of the engine's own, because the engine's own updates become known within one broker call, and an update that has waited longest without matching is most likely about an order placed from a broker's app.
