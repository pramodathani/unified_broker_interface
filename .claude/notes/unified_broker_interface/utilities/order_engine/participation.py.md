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

## Why a caller's change to a slice adjusts `placed_quantity`

The parent sizes each slice from what is left of the total, counted by `placed_quantity`. A slice the caller cut from 500 to 300 placed 200 less than was counted, so `on_leg_modified` takes 200 off the count and a later slice places it; a slice the caller raised takes from the later ones. The parent's total stays what the caller first asked for, and the new count is recorded with `parameters_changed` so a restart keeps it.

## Whole lots (fixed 2026-10-02)

A slice was never rounded to whole lots, and the counters were saved before the send, so a refused slice was counted as placed; on a NIFTY option (lot 75) the order counted all 750 as placed, sent nothing, and stayed `received`. Slices are now cut down to whole lots before anything is counted, a share under one lot leaves `counted_volume` alone so volume keeps accumulating, and any refusal from `send_slice` restores the counters. `lot_size` uses the chosen broker's lot, or the largest any broker lists before a broker has been chosen (the brokers agree on lots in practice), because `chosen_broker` is None until the first slice.
