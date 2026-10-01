# grid_part.py

## Answering fills from state (2026-10-02)

Today's grid reacts in `on_leg_update` to the leg that just filled. A plan settles the whole tree from the fills as they stand on every event, so the grid answers every filled rung whose leg id is not yet in `answered`, and records the id before placing the opposite. Settling twice, or replaying after a restart, therefore places nothing twice.

## The cap

As in today's grid, the cap is checked only after a new fill has been answered, by cancelling resting rungs on the side that would add to the position. Checking on every settle would ask the broker to cancel the same rung again while its first cancel was still unconfirmed.

## The centre

The last traded price is read in `prepared_own_memory`, before the parent is recorded, so a quote with no last price is refused with 503 and no parent, as today. The tick size is worked out there from the catalogue, because the plan remembers tick sizes only after every part's record is built.

## What differs from today's grid

The answer is the plan's: `legs` with each order's outcome, rather than `centre_price` and `rungs`. Its legs carry the part's path as their role rather than `rung`.
