# Notes on `unified_broker_interface/utilities/order_engine/utilities/trails_condition.py`

## Why an engine-side trailing condition exists beside the trailing pricing

The design's worked example is a trailing stop that exits through TWAP. A native trailing stop cannot do that: whatever the broker triggers is one stop-limit. A trigger that trails in the engine lets the exit order be priced and, from stage 3, executed any way the order's other slots say. The trade-off is the one today's hidden stop makes: it does nothing while the engine is down, so the `trail` pricing stays the default for trailing stops.

## Why the direction comes from the sending side

The condition follows the price that matters to the order it triggers: the highest price for an order sent as a sell, which is the exit of a long, and the lowest for a buy. Unlike `PriceCrossesCondition`, it has no level of its own, so there is no default direction to take from the opening side.

## Stale quotes (2026-10-05)

A quote marked `stale` used to be read like any other, so with holding off a stale touch fired a `limit_if_touched` and sent its limit at once (found in the group 3 walkthrough). The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so the price may be minutes old. `LimitMarketableCondition` already ignored such quotes; this condition now does the same, returning False before its memory is touched, so a stale tick neither fires nor counts towards, nor resets, a confirmation. A time-based age limit was not added, because staleness is already decided from broker health in one place.
