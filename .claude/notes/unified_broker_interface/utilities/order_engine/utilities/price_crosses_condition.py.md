# Notes on `unified_broker_interface/utilities/order_engine/utilities/price_crosses_condition.py`

## Why it copies `PriceTrigger`'s rules rather than using the class

`PriceTrigger` is a `SyntheticOrder` subclass that owns its whole parent: it keeps `reached_ticks`, `reached_since` and `triggered_at` in the flat `parent.parameters` and decides it has fired from whether any leg exists. Those are exactly the habits that stop parts sharing a parent, so the condition reimplements the same rules (default directions, `double_last`, `held`, a tick that misses restarting the count) with its memory handed in by the part. The behaviour was kept identical so a preset built on it matches today's type.

## Why one default direction serves entries and stops

With no direction, a body `BUY` waits for the price to fall and a `SELL` for it to rise. For an entry that is market-if-touched's buy-the-dip meaning. For a `protect` part, the body's side is the side that opened the position, so a long (body `BUY`) is protected by a condition that fires when the price falls, which is a stop's meaning. Both come out of the same rule because the direction is taken from the opening side, not the sending side.

## Why `opposite_touch` is read against the sending side

The hidden stop watches the touch its exit would trade against: the bid for a sell. A part tells the condition the side it will send on, so `opposite_touch` means the same thing for an entry and for an exit.

## Stale quotes (2026-10-05)

A quote marked `stale` used to be read like any other, so with holding off a stale touch fired a `limit_if_touched` and sent its limit at once (found in the group 3 walkthrough). The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so the price may be minutes old. `LimitMarketableCondition` already ignored such quotes; this condition now does the same, returning False before its memory is touched, so a stale tick neither fires nor counts towards, nor resets, a confirmation. A time-based age limit was not added, because staleness is already decided from broker health in one place.
