# `trailing.py`

## Why the two trailing types are one class

A trailing stop and a trailing entry sound like opposites and are the same object. A trailing stop protecting a long is a *sell* stop that ratchets **up** behind a rising market. A trailing entry to buy is a *buy* stop that ratchets **down** behind a falling one. Everything else — the watermark, the distance, the step threshold, the limit offset, the refusal to move backwards — is identical, and the direction of every comparison in the file is decided by the side of the stop and nothing else.

Writing them as two files would have meant writing the ratchet twice with every inequality flipped, which is exactly the kind of duplication where a sign gets reversed and nothing fails loudly: a trailing stop that follows the price both ways simply never fires, and looks like a quiet day until the one it matters on.

So the two subclasses each answer one question — which side is the stop on — and hold their own docstring explaining what that means for somebody trading it.

## Why the stop stays at the broker

The Atlas offers two builds. The resting build keeps a native stop-loss limit at the exchange and moves its trigger with `modify`. The hidden build remembers the level here and fires a marketable limit when the price crosses it, which sends no modify traffic at all.

The resting build is here because of the one thing it has: it works while this process does not. A trailing stop that has been ratcheting up all afternoon is protecting real profit, and the moment the engine, the machine or the quote feed stops is exactly the moment it is most needed. The hidden build's saving is order traffic, which `step_ticks` and the engine's re-pricing throttle already address.

The hidden build is not lost. `hidden_stop` is that type, and somebody who wants a hidden trailing stop is asking for a combination that would need both, which is not built.

## Why the percentage is measured against the watermark

`trail_percent` of 1 on a position entered at 1000 that has run to 1100 gives a distance of 11, not 10. The distance widens as the trade goes further.

That is what somebody asking for a percentage almost always means: risk a proportion of what the position is worth now, not a proportion of what it was worth when it was opened. Measuring against the entry instead would make the trail proportionally tighter the better the trade did, which is the opposite of what a percentage is usually for.

## What the offline scenarios caught

`modify_leg` builds its request from the order as the **broker's own book** holds it, not from what the engine thinks it placed. The first run of these scenarios failed with "a LIMIT order takes no trigger_price", because the harness seeded a plain limit order into the fake order book while the type had placed a stop.

That was a fixture bug rather than a code bug, but it is worth writing down, because it means a broker whose book reports an order's type differently from how it was sent will break every re-pricing type, and the failure arrives as a validation error on the modify rather than anywhere near the cause.
