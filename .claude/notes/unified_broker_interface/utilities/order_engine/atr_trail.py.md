# `atr_trail.py`

## Why `trail_points` is still required

The bars are built from this order onwards, so a fourteen-period average of five-minute bars needs seventy minutes before it exists. Until then the stop has to trail at something, and that something has to come from the caller, because there is no defensible default distance for an instrument the engine knows nothing about.

The switch from the fixed distance to the average happens quietly the first time there are enough bars. An order placed at ten past three will never get there and will behave as a fixed trail for its whole life, which the class docstring says plainly.

## The ratchet beats the average, which is correct

An interesting interaction showed up in the offline scenario and is worth recording because it looks like a bug and is not.

The average range widens when the market gets volatile, which widens the trail, which would move the stop *further* from the market. The ratchet in `TrailingOrder.improves_trigger` refuses that: a stop never moves backwards.

So a widening range never loosens an existing stop. It only slows how fast the stop follows a market that is still going the right way. That is the right behaviour — the whole reason to trail is to keep what has already been made — and it means the average-range trail is most visible early in a position and least visible late in one.

## Why the true range counts gaps

A bar's true range is the greater of its own high-to-low span and the distance from the previous bar's close. The second half is what counts a gap as movement rather than ignoring it, and in India that matters more than in most markets: an overnight gap is frequently the whole of a day's move, and a volatility measure that ignored it would report a quiet market on the days that are least quiet.
