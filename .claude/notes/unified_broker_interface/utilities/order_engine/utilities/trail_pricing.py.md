# Notes on `unified_broker_interface/utilities/order_engine/utilities/trail_pricing.py`

## Why it copies `TrailingOrder`'s rules rather than using the class

`TrailingOrder` in `utilities/trailing.py` is a `SyntheticOrder` subclass that finds its stop by the role `stop` and keeps `watermark` in the flat `parent.parameters`, the habits that stop parts sharing a parent. The pricing reimplements the same rules with its memory handed in by the part: start from the last price when placed, move the best price only in the favourable direction, trigger `points` or `percent` behind it, limit `limit_offset` past the trigger, round both onto the tick for the stop's side, and move only by at least `step_ticks`. The offline scenarios send the same trigger and limit prices as today's type would for the same ticks.

## Why the best price is called `best` rather than `watermark`

It is the same idea, but inside a part's own `pricing_memory` there is no other value to tell it apart from, and `best` reads more plainly. It is kept in Redis between ticks without a recorded event, as today's trailing stop keeps its watermark, so a restart resumes from the last recorded parameters rather than the latest best price; the stop itself is at the broker and still protects the position.

## Why a pricing can now move a resting order

`moves` and `moved_prices` were added to the pricing interface for this class. The other pricings answer False to `moves`, and `OrderPart.move` asks only a pricing that moves. Every move goes through `SyntheticOrder.reprice_leg`, so the repricing throttle, the daily cap and the rate budget apply exactly as for today's trailing stop.

## What is not carried over yet

`TrailingOrder.on_leg_modified` re-anchors the watermark when a caller changes the stop by hand. A plan part does not yet react to a caller's change to its order, so a hand-moved trailing stop in a plan will be moved back towards the trail on the next tick that calls for a move.

## A caller's changes (added 2026-10-02)

`best_for_trigger` is the inverse of `prices_from` before rounding, matching `TrailingStop.watermark_for_trigger`. With `percent` the result is not rounded, so `best` can carry many decimal places; it is only compared and multiplied, so this is harmless.

## Never through the market (2026-10-04)

`moved_prices` refuses a move that would put a sell stop's trigger at or above the last price, or a buy stop's at or below it. For a plain trail that cannot happen, since the trigger only moves when the best price improves. For `AtrTrailPricing` the distance shrinks as the market calms, so the trigger rose while the best stayed put: in the research run, at a best of 1031 and a last of 1024, the engine sent a sell stop with trigger 1026.70, which a broker either refuses or fires at once into a limit resting above a falling market. The scenario `an_average_range_trail_never_moves_its_stop_through_the_market` replays that path.
