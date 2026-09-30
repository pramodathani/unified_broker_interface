# Notes on `unified_broker_interface/utilities/order_engine/utilities/trails_condition.py`

## Why an engine-side trailing condition exists beside the trailing pricing

The design's worked example is a trailing stop that exits through TWAP. A native trailing stop cannot do that: whatever the broker triggers is one stop-limit. A trigger that trails in the engine lets the exit order be priced and, from stage 3, executed any way the order's other slots say. The trade-off is the one today's hidden stop makes: it does nothing while the engine is down, so the `trail` pricing stays the default for trailing stops.

## Why the direction comes from the sending side

The condition follows the price that matters to the order it triggers: the highest price for an order sent as a sell, which is the exit of a long, and the lowest for a buy. Unlike `PriceCrossesCondition`, it has no level of its own, so there is no default direction to take from the opening side.
