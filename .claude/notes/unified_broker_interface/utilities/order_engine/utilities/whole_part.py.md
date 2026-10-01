# whole_part.py

## Why the kept-whole types are parts rather than wrapped old classes (2026-10-02)

The design says each kept-whole type is ported as a single part that owns its orders and memory, so it can sit inside a join. Wrapping today's class instead would have meant faking a whole parent for it: today's classes change the parent's state, answer the caller and read every leg of the parent, none of which a part may do. Porting keeps the rules and drops that machinery.

## Why it subclasses `OrderPart`

`PlanOrder` and the joins treat every order part alike: `run` builds a record per part, the ticks walk `order_parts()`, and joins call `start`, `settle`, `traded`, `set_target`, `cancel_rest`, `is_started` and `is_done`. Subclassing `OrderPart` with no trigger and fixed pricing gives a kept-whole part all of that with neutral defaults, so `PlanOrder` needs only one new hook, `prepared_own_memory`, called when the plan is placed.

## Telling its broker orders apart

Every leg a part places carries the part's path as its role, so a kept-whole part tells its own orders apart by leg id, and keeps the ids it has acted on in `own_memory`. `remember` records the memory with a message, so the parameters event carries it and a restart replays it.

## Settings are checked by the part

Each type's settings are checked by its own class in `settings_problems`, which the reader turns into `bad_setting` problems, rather than in the preset expander. That keeps every type's rules in one file, as the user's style asks.

## `inventory` (2026-10-02)

The grid and the two-sided quote both measure the net position their own fills have built, in the same way, so `inventory` moved here from `GridPart` when the quote was ported.

## Stopping (2026-10-02)

`cancel_rest` records `stopped` for every kept-whole part before cancelling what rests. The two-sided quote and the exposure hedge end only once stopped; the grid and the scale with profit-taker stop placing anything new once stopped, so a rung that fills after its join cancelled the grid is not answered with a fresh order. `finish_when_done` is `OrderPart`'s done rule, shared by all four.

## Stopped with nothing placed (2026-10-02)

`OrderPart`'s done rule waits for every broker order to finish, and a part with none never finishes. A two-sided quote, exposure hedge or strategy stop's exits stopped before placing anything would then hold the plan open for the rest of the day, so `finish_when_done` ends a stopped part with no orders as cancelled.

## `opened_instruments`

Set by the reader on a kept-whole Then child, beside `opened_by`: the instrument each of the first plan's orders trades, None for the parent's own. The strategy stop's exits read it to know what to watch.
