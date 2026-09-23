# `accumulation.py`

## Why each purchase rests instead of chasing

This looks like a time-weighted order and differs in intent, and the difference decides the pricing.

A time-weighted order is working a decision already made. It has a window, an obligation to finish, and it gets more aggressive as the window runs out. An accumulation has none of those: it is a standing arrangement with no deadline, and paying the spread on every purchase several hundred times over a year is a real cost against a strategy whose entire edge is patience.

So each purchase rests on its own side of the book and simply does not fill if nobody meets it. The order sits until the day ends and the next purchase is a new order at the new price.

The Atlas suggests a chaser for each purchase, which would be better still and would need one parent to run another. The engine has no nested parents, and adding them for this would be a large change for a small gain over resting. Somebody who would rather be certain of accumulating should ask for a chaser or a plain marketable order on a schedule.

## Why the schedule is measured from placement

"Every thirty minutes, eight times" means what it says whenever it was started, rather than depending on a clock time the caller would also have to supply. That makes it the one timed type in the package with no `at_time`, and it reads the same clock the tick reads for the reason every timed type does.
