# `daily_stop.py`

## The gap case is the whole point

Re-placing a stop every morning is bookkeeping. What makes this worth being a type is the morning when the market has already opened past the stop.

A stop-loss limit whose trigger is on the wrong side of the last traded price is either refused outright by the broker or fires the instant it is accepted, at whatever the gap left behind. Neither is what anybody wanted from a stop they set the night before, and both happen on exactly the mornings that matter.

So the position is closed instead, with a limit priced past the touch. That at least chooses a price rather than taking one, and it ends the parent rather than leaving a stop that will never work. The Atlas names this case specifically, and getting it wrong would make the type worse than useless: it would look like protection every ordinary morning and fail on the one that counted.

## Why it arms at 09:20 rather than at the open

The first minutes of a session are the pre-open auction settling. A stop placed into that can be triggered by a price that lasts seconds and means nothing, which is the same freak-trade problem that got stop-loss-market orders withdrawn in the first place.

Five minutes is enough for the last traded price to mean something and is early enough that a real gap is still being acted on promptly. `arm_at` moves it for anybody who disagrees.

## Why nothing is placed when the order is accepted

A daily stop is a statement about tomorrow morning and every morning after it. Placing one immediately would be doing something different from what was asked, and somebody who wants a stop resting this afternoon is asking for an ordinary stop-loss limit order, which they can simply send.

`armed_on` holds the date in the exchange's own timezone rather than a timestamp, because the question being asked is "have I already done this today", and a date answers it without any arithmetic about where the boundary falls.
