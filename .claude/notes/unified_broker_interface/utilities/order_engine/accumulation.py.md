# `accumulation.py`

## Why each purchase rests instead of chasing

This looks like a time-weighted order and differs in intent, and the difference decides the pricing.

A time-weighted order is working a decision already made. It has a window, an obligation to finish, and it gets more aggressive as the window runs out. An accumulation has none of those: it is a standing arrangement with no deadline, and paying the spread on every purchase several hundred times over a year is a real cost against a strategy whose entire edge is patience.

So each purchase rests on its own side of the book and simply does not fill if nobody meets it. The order sits until the day ends and the next purchase is a new order at the new price.

The Atlas suggests a chaser for each purchase, which would be better still and would need one parent to run another. The engine has no nested parents, and adding them for this would be a large change for a small gain over resting. Somebody who would rather be certain of accumulating should ask for a chaser or a plain marketable order on a schedule.

## Why the schedule is measured from placement

"Every thirty minutes, eight times" means what it says whenever it was started, rather than depending on a clock time the caller would also have to supply. That makes it the one timed type in the package with no `at_time`, and it reads the same clock the tick reads for the reason every timed type does.

## Why a purchase never goes past the caller's price

`buy_once` priced every purchase at the book's own touch and never read the caller's `price`. In the live test of 2026-09-27 an accumulation asked to buy at ₹20.50 was placed at ₹22.50, the weekend quote's bid, and on a trading day would have filled at a price the caller never agreed to. The caller's limit is now a cap for a buy and a floor for a sell, as it is for the volatility order, and the book's touch is used only when it is better. With no touch on that side the caller's price is used rather than refusing, since the caller has already named a price they will accept. An order with no price, such as a MARKET body, keeps the old behaviour.
