# `implementation_shortfall.py`

## Why a geometric decay

Implementation shortfall is a large literature and most of it is about the shape of the curve. What was built is the simplest shape that has the right property: each slice is a fixed fraction of the one before, and the fraction is the caller's urgency dial.

The reasoning is that the shape matters much more than the curve. Front-loading at all is the decision; whether the tail falls off as a geometric series or as the square root of remaining time is a refinement worth having only once somebody is measuring their own fills against the benchmark. A geometric decay is also the only shape a reader can evaluate in their head: urgency 1 means each slice is half the last, so a ten-slice order is half done after two.

The range is capped so that urgency 0 is exactly a time-weighted order. That gives the dial a meaningful zero and makes the subclass provably a generalisation of its parent rather than a different thing wearing its clothes.

## Why the arrival price is recorded even though nothing reads it

The whole type is named after a number — the gap between the price when somebody decided and the price they got — and that number cannot be computed later unless the first half of it was written down at the time.

Nothing in the engine reads `arrival_price`. It is there so that somebody reading the event log afterwards can actually measure whether the front-loading helped, rather than assuming it did. A quote that cannot be read is recorded as absent rather than refusing the order, because the slicing works either way and refusing would trade a working order for a missing statistic.
