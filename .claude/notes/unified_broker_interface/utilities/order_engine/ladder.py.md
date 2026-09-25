# Notes on `unified_broker_interface/utilities/order_engine/ladder.py`

## What it is for

Somebody who thinks an instrument is worth buying between 995 and 1000 does not have to choose which of those two numbers to bid. A ladder bids at both and between, so what they pay on average depends on how far the market comes to them rather than on one number guessed in advance.

## Why the quantity is divided rather than repeated

The caller's `quantity` is the whole order, split between the rungs. A ladder of a hundred over three rungs is 34, 33 and 33.

The other reading — a hundred at every rung — is what somebody gets if they are not paying attention, and the cost of guessing wrong is three hundred units rather than a hundred. Dividing is the reading where a mistake is small.

A ladder therefore needs at least as much quantity as it has rungs, and says so rather than silently dropping the rungs it cannot fill.

## Why every rung rounds towards the passive side

A range that does not divide evenly into ticks produces prices between them. Rounding a buy's rungs down and a sell's up means every rung rests where it was meant to rest; rounding to the nearest would occasionally put a rung a tick further into the market than the caller's own range allowed, which is the one thing a ladder is not for.

## Why a ladder is not a chaser

Nothing here reacts to anything. Every rung is placed once and left, and the type is finished the moment the last one is sent. That is what makes it belong with the freeze slicer in the stateless tier rather than with the types that watch fills.

The rungs are ordinary limit orders at a broker, so they keep working whether or not the engine is running, which is the property the `docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`) reasoning about native orders keeps coming back to.
