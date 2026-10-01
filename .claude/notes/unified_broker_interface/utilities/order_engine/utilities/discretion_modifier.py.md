# Notes on `unified_broker_interface/utilities/order_engine/utilities/discretion_modifier.py`

## Why it copies the discretionary type's rules

Taking when the touch is within `points`, the two-tick buffer capped at the reachable price, taking all that rests by default, and reducing or cancelling the visible order before the taking one is sent are the rules of `discretionary.py`. The offline scenarios `a_plan_discretionary_order_*` send the same requests as `a_discretionary_order_*`.

## Why only the first broker order is visible

Today the taking order has its own role, `discretion`, so it is never mistaken for the visible one. In a plan every broker order of a part has the part's path as its role, so the visible order is the part's first; a taking order that rests is never taken from again.

## Why it is refused with slicing

With pieces there would be several visible orders and the taking orders among them, and the rule for which to take from would no longer be today's. `OrderPart.set_target` now shares the wanted quantity across all resting orders, oldest first with the last taking the rest, so a part holding a visible order and a taking order is resized correctly under a join.
