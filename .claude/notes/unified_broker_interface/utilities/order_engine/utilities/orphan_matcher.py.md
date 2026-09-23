# Notes on `unified_broker_interface/utilities/order_engine/utilities/orphan_matcher.py`

## The gap this exists to narrow

The engine records a leg and commits before sending it, so a crash in between leaves a leg in `sending` with no broker order id and possibly a live order at the broker. The window is one HTTP round trip, 100 to 300 milliseconds.

It applies only to an entry leg. A stop, a target or an OCO sibling is invented by the engine and carries the parent's own tag, so attributing one is an exact string match with no ambiguity at all. The entry carries the caller's tag unchanged, by the decision taken on 2026-09-23 that a caller's tag is theirs, and that is what leaves the order in the broker's book with nothing naming its parent.

## Why it would rather give up than guess

Wrong attribution is the worst outcome available. Attaching the wrong broker order to a parent means the engine then hangs a stop and a target on a position it does not own, and cancels or reduces an order somebody else placed. Compared with that, refusing to attribute a leg and parking its parent for a person to look at is cheap.

So every field the engine chose has to agree — the identifier as sent, side, product, order type, validity, quantity in the broker's own terms, price and trigger to four places, and the tag, with both being absent counting as agreeing — and the order's timestamp has to fall inside the window the request was in flight. Two candidates and zero candidates both end the same way.

The residual risk is stated plainly rather than engineered away: if the same account placed a second order at the same broker, on the same instrument, side, product, type, quantity, price and tag, within seconds, by any route, this can still attribute the wrong one. Nothing here makes that impossible.

## Why a stale book stops the pass entirely

If a broker's `polled_at` is more than a minute old, the matcher does not run and the parent is parked. A book that has not been read recently may simply not contain the order yet, so every leg would look unattributable — the right answer for the wrong reason, and one that would train a reader to ignore the alert.

## Why an order with no timestamp is still allowed to match

A broker that reports no `order_timestamp` should not by itself make an order unattributable, because that is a property of the broker rather than of the order. The other seven comparisons still have to agree, and the unclaimed-set filter still applies. This is the one place the matcher is deliberately lenient, and it is recorded here so that a later reader knows it was a choice.
