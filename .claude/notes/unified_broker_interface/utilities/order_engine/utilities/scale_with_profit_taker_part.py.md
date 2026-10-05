# scale_with_profit_taker_part.py

## Rungs and profit-takers (2026-10-02)

Today's type tells a rung from a profit-taker by the leg's role, `slice` or `target`. Every leg of a part has the part's path as its role, so the part tells them apart by side: a rung is on the body's side and a profit-taker on the other. Which rung each broker order belongs to is kept in `rung_of_leg`, by leg id, and every answered fill in `handled`, both recorded with a message so a restart answers nothing twice.

## The rungs come from `LadderExecution`

The prices and quantities come from the plan's ladder execution, so the rungs are exactly what the `ladder` preset would place. The ladder needs the tick size, which the plan remembers only after every part's record is built, so the rungs are laid out in `start` rather than when the plan is placed; `prepared_own_memory` only refuses a quantity smaller than the number of rungs, before the parent is recorded, as today.

## When it is done

Today's type sets `FINISHES_WITH_LEGS = False` and stays open even once every rung has used its cycles and nothing rests. The part uses `OrderPart`'s rule and is done once every one of its broker orders has finished. While cycles remain, a filled order is always answered by a new one in the same settle, so that point is reached only after the last allowed profit-taker has filled, and the plan can then complete rather than sit open until the day ends.

## `place_leg` returns the leg's id

The third value `place_leg` returns is the leg's id, which `OrderContext.place_leg`'s docstring had called the leg; it was corrected when this part first used the value.

## Profit-takers from the fill (2026-10-05)

A profit-taker is sized from the rung's `filled_quantity`. A rung the caller cut to 5 that filled 5 got a profit-taker of 10, leaving the account short 5. The rung's remembered size is still used when it is placed again.
