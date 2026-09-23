# `good_till_triggered.py`

## Why this is one class attribute and an expiry

The whole of it is `LimitIfTouched` plus `CARRIES_OVERNIGHT = True` plus a date it gives up on. That is not an accident of implementation — a broker's good-till-triggered product is exactly a limit-if-touched order that their system keeps running after the session ends, and the only thing that made it hard here was the machinery in `DayRoll` and the recovery window, which is shared.

## What it does not protect against

Neither this nor a broker's own version protects against a gap. The trigger is checked against a live price, so an instrument that opens twenty per cent below the level fires at the open and places its limit into a market that has already moved past it.

That is inherent rather than a limitation of this build: nothing that watches prices can act on a price that never traded. It is stated in the class docstring because a multi-day stop is precisely the thing people assume protects them overnight.

## Why it expires at all

A trigger nobody has thought about for a year is more likely forgotten than intended, and one that fires eleven months after it was set will fire into a position and a view that no longer exist. Thirty days by default and a year at most, after which the parent is closed rather than left in the record for ever.

The expiry is computed as arithmetic on the same clock the tick reads rather than as a calendar calculation on `datetime.now`. The first version used the calendar and the offline scenario never expired, because the test freezes one clock and not the other — the same class of mistake as the TWAP reading its schedule from one clock and checking it against another. India keeps no daylight saving, so a day really is 86,400 seconds and nothing is lost by doing it this way.
