# Notes on `unified_broker_interface/utilities/order_engine/stepped_stop.py`

## Why it subclasses `TrailingStop`

The plan said `TrailingOrder`. `TrailingStop` already says the stop trades the closing side and that the parent is `protecting` once it rests, which is exactly what a stepped stop needs, and its last rule turns it into a trailing stop. Subclassing it keeps the chain shallow (`TrailingOrder` → `TrailingStop` → `SteppedStop`) and lets a trailing rule hand the rest of the trade to the inherited `on_price_tick` by writing `trail_points` and `watermark` into the parameters.

## Why gains are measured from `entry_price` rather than from the stop

The Atlas's rule table is written in profit: "at +20, move the stop to breakeven". Profit is measured from where the position was opened, which the engine does not know for a position it did not open, so the caller gives it. `stop_at_gain` uses the same origin, so 0 means breakeven whatever the first stop was.

## Why several milestones on one tick are one modify

A gap past two milestones would otherwise send two modifies in the same second for one stop, the second making the first pointless. Only the last reached milestone's level is sent, and `rules_applied` records how many were reached, so none is applied twice.

## Why `on_leg_modified` does nothing before the trail

`TrailingOrder.on_leg_modified` works the watermark back from the caller's trigger using the trail distance, which a stepped stop does not have until its trailing rule is reached; calling it earlier would raise. Before the trail, the milestones do not depend on where the stop is, so the caller's trigger can simply stand.
