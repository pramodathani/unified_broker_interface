# `chaser.py`

## Why the step is taken from the order and not from the book

`step` moves the order one step from where the order currently is, not one step from wherever the bid is now. The difference shows up when the market moves while the chaser is walking.

Stepping from the book would let a bid that ticked away drag the order backwards, so a chaser told to walk towards the offer would sometimes retreat from it, and on a choppy instrument it could walk for an hour without getting anywhere. Stepping from the order gives the monotonic behaviour the name promises: each step is strictly more aggressive than the last, whatever the book does around it.

The book still bounds the result. A step is never allowed past the opposite touch, because an order there already fills and moving further is paying for nothing.

## Why it stops at the touch rather than crossing

Reaching the opposite touch is where a chaser's walking ends. An order resting at the offer fills against whatever is there, and there is nothing further to walk to; moving beyond it only widens the price the order is willing to pay without making the fill any faster.

Crossing is a separate decision with a separate parameter. `cross_after_seconds` is about giving up on patience after a stated time, and when it is not set the chaser simply rests at the touch, which is the right default: nothing was said about giving up, so nothing gives up.

## Why it runs on the price tick rather than the clock

A chaser waits for a time and watches a price, so it could plausibly have set both `WANTS_CLOCK` and `WANTS_PRICES`. It sets only the second, and reads the time from the price tick's own `now`.

Two beats would mean two places that can decide to move the same order, arriving a few hundred milliseconds apart and each spending a request. More importantly it would mean a step computed from a quote read on a different beat than the one that decided the step was due, which is the same class of mistake as reading a schedule from one clock and checking it against another.
