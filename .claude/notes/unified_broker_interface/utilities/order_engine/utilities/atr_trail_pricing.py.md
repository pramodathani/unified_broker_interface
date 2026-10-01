# Notes on `unified_broker_interface/utilities/order_engine/utilities/atr_trail_pricing.py`

## Why it wraps a trail rather than extending one

Today's average-range trail subclasses the trailing order and overrides only how far behind it sits. Here the distance depends on bars kept in the pricing's memory, which `TrailPricing.distance` is not given, so the class works the distance out and hands each tick to a `TrailPricing` built at that distance. The trail's own memory, `best`, sits in the same memory beside `bars`. The offline scenarios `a_plan_average_range_trail_*` send the same requests at the same prices as `an_average_range_trail_*`.

## The bars across a restart

The bars change on every tick and are recorded with an event only when the stop moves, so a restart can lose the bars built since the last move, as today's type loses whatever was saved without an event. The stop never moves back, so a shorter history can only delay a widening, not loosen the stop.

## The design's `trail` with `atr`

The design lists `atr` as a third way to give a trail's distance. The reader keeps that shape: `trail` with an `atr` object, which needs `points` as the fallback and refuses `percent`.
