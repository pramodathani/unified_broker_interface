# Notes on `unified_broker_interface/utilities/order_engine/utilities/chase_pricing.py`

## Why it copies the chaser type's rules

Starting at the own touch, stepping from the order's own price rather than from the book, never stepping past the other side's touch, and crossing to that touch once `cross_after_seconds` has passed are the rules of `chaser.py`. The offline scenarios `a_plan_chaser_*` send the same requests as `a_chaser_*`.

## Why the clock starts on the first tick

`priced_body` is not given the time, and the plan sends orders from places that do not all know it, so the clock starts on the first tick after the order rests. Today's chaser starts it when the order is placed; with ticks every second the difference is at most a second, and in the offline scenarios the first tick and the placement share a moment, so the steps fall on the same ticks.

## Why the memory is recorded with each step

A plan part's memory survives a restart only if an event records it. `OrderPart.move` records the pricing memory when an order moved or when the memory was first set, so the chase's start and last step are kept. A step that changed nothing, because the order already sat at the touch, updates `stepped_at` without an event; after a restart the order waits from the last real step instead, which sends nothing different, as `a_plan_chaser_keeps_its_clock_across_a_restart` shows.

## Stale quotes (2026-10-05)

The group 6 walkthrough found every moving pricing acting on a quote marked `stale`: a peg followed a stale bid, a chaser crossed to a stale offer of 1005, an underlying peg moved on a stale index. The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so its price may be minutes old. This pricing now treats a stale quote as no quote, as `LimitMarketableCondition` always did: it neither places from it nor moves on it, and the next fresh quote moves the order as usual.
