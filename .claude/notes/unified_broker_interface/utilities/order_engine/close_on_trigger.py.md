# Notes on `unified_broker_interface/utilities/order_engine/close_on_trigger.py`

## Why `child_order` returns the caller's own order

`PriceTrigger.on_price_tick` asks `child_order` for an order before calling `fire`, and stops if it gets None. The closing order cannot be built there, because it depends on the position after the cancels, and a missing position must complete the parent rather than keep it waiting. So `child_order` hands back the caller's order, which carries the product and side, and `fire` builds the real closing order. Overriding `on_price_tick` instead would have meant copying the trigger and `trigger_on` confirmation logic.

## Why the leg's role is `close`

A leg with the role `entry` counts against the daily cap as a new position and is stopped when the cap is near. An exit must be allowed to use the exit reserve, so the closing leg is recorded as `close`, the role `square_off` uses.

## Why it closes the position rather than a named quantity

The Atlas describes the exit as closing the position. A position that has grown or partly closed since the order was armed would otherwise be over- or under-closed, and over-closing opens a new position the other way.
