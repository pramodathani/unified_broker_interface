# `participation.py`

## Why the quote's cumulative volume rather than counting trades

`volume` in the unified quote is the day's cumulative traded quantity as the exchange publishes it, so the difference between two ticks is exactly what traded in between. Counting trades from the tick stream would give the same answer more slowly, with gaps whenever a tick was dropped or the feed restarted, and with a different answer depending on how long the engine had been running.

The cumulative number is also self-correcting. A missed tick costs nothing: the next one carries the whole interval's volume, and the slice that follows is correspondingly bigger.

## Why a share below one unit is remembered rather than rounded

A one per cent participation in a market trading fifty units a tick earns half a unit each time. Rounding up sends a whole unit for half a unit's worth of cover, which over an afternoon is double the participation the caller asked for. Rounding down sends nothing, ever, on a quiet instrument.

So `counted_volume` is only advanced when a slice actually goes out. The volume that earned a fraction stays uncounted and adds to the next tick's, until it is worth a whole unit. That makes the participation rate right on average rather than right on each tick, which is what the rate means.

## Why it has no deadline and why that is stated

A percentage-of-volume order in a market that stops trading stops trading too. It can finish the day with most of the order undone, and nothing about it will complain, because from the inside "the market is quiet" and "I am nearly finished" look the same.

`most_slices` bounds the requests rather than the outcome. The real answer is that somebody has to watch it, or wrap it in a time stop, and saying so in the class docstring is better than adding a deadline that would quietly turn it into a different type at the worst moment.
