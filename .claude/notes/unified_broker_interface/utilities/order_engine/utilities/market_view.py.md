# `market_view.py`

## Why this exists beside `PriceReference`

They read the same quote and they look alike, and the temptation to merge them should be resisted, because they differ in the one thing that matters: what to do when the quote does not carry what was asked for.

`PriceReference` is answering a caller who is holding an HTTP connection open. A midpoint that cannot be computed because the book has no offer is a request that cannot be honoured, and the honest answer is a 503 with a message saying so.

`MarketView` is answering a tick. Nobody is waiting, the same question will be asked again in a second, and the book that was empty a moment ago usually is not. Raising there would mean every watching type wrapping every price read in a try block to turn an exception back into "do nothing", which is the shape of code that eventually swallows a real error by accident.

So every reader returns `None`, and a type that cannot act without a price returns `False` for that tick and looks again. Merging the two would have meant one of the two behaviours pretending to be the other.

## Why prices out of the book are snapped and the midpoint is not

The snapping is the same fix, for the same reason, as the one recorded at length in `PriceReference.number`. A quote is built from JSON floats, so an offer of 1000.10 arrives as 1000.0999999999999. Rounding that down, which is what a buy does, gives 1000.05 — a whole tick away and the wrong level of the book entirely.

The midpoint is deliberately left alone. A midpoint of a one-tick spread belongs exactly between two ticks, and which of them it should become depends on the side of the order, which `MarketView` does not know at the time it computes the midpoint. Snapping it there would round a buy's midpoint up into the offer, turning a passive order into an aggressive one.

## Why `moved` takes a side and a direction rather than a signed number of ticks

A buy gets more aggressive by moving up and a sell by moving down, so "one tick towards the market" is `+tick` or `-tick` depending on the side. Every caller that worked this out for itself would be a place the sign could be wrong, and a sign error here does not fail loudly: it places an order one tick further from the market than intended, which looks like a slow day rather than a bug.

## `is_stale`

Added for `virtual_limit`, which must not send an order on a quote whose owning broker went silent: the unified quote layer keeps such a quote in `unified:quotes:live` with `stale` set to true. The other types still ignore the flag, as they did before; whether they should is an open question rather than a decision.
