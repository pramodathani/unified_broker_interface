# Notes on `unified_broker_interface/utilities/order_engine/scale_out.py`

## The one place the OCO rule is wrong

`OneCancelsOther.rebalance` reduces every other exit by whatever just filled. That is right when there are two exits covering one position, and wrong here.

A scale-out's targets are *tranches*: three targets of three each, adding up to the nine the entry filled. When the first takes its three, the other two are still the right size — they were always meant to take the remaining six between them. Reducing them by three each would leave three units of cover for six units of position.

The stop is different. It covers everything not yet taken off, so it is the one leg that has to follow every fill down. So `rebalance` is overridden to reduce only the stop, and `grow_exits` likewise grows only the stop as the entry fills further.

It is worth being explicit that this is an override of inherited behaviour rather than an addition, because reading the bracket alone would give the wrong idea of what a fill does here.

## Why the stop moves to breakeven rather than being replaced

After the first target fills, the stop is moved to the entry's average price with a price modification, not cancelled and re-placed.

A trade that has reached its first target has paid for itself, and a stop still sitting below the entry is risking money the position has already made. Moving it is the point. Doing it as a modification rather than a replacement means there is never a moment with no stop at the exchange, which is the same reasoning that makes the OCO reduce rather than cancel.

`stop_at_breakeven` is recorded in the parent's parameters once it has been done, so a later fill on a second target does not move a stop that has already moved.

## Why fewer units than targets collapses to the last target

An entry that filled two units against three targets cannot be split three ways. Rather than placing an order for zero, or one for each unit and leaving the third target empty, the whole of it goes on the last target — the furthest one, which is the one somebody scaling out would keep if they had to choose.
