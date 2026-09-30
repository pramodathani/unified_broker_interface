# Notes on `unified_broker_interface/utilities/order_engine/utilities/then_part.py`

## Why the join settles instead of reacting to changes

Every event makes the plan order call `settle` on the whole tree. The Then join then sets the child's target to what the first plan has filled now, and the child compares that with its resting order. Nothing is added or subtracted from a running total, so an update delivered twice, out of order, or replayed after a restart cannot count a fill twice. This is the shape that makes the OCO bug fixed on 2026-10-01 (a second partial fill taken off the sibling twice) impossible here rather than merely fixed.

## Why the child grows by changing its order, not by adding orders

The design document said a child "grows by adding pieces". With only `all_at_once` execution, a child is one resting order, and changing its quantity is one request where a new order would be another order message and another leg for the exits to track. When execution values that split an order arrive in stage 3, growing a sliced child will need revisiting.

## Why `cancel_first_on_child_fill` defaults to false

It is a bracket's rule, and the `bracket` and `cover` presets set it. Today's OTO does not cancel its entry when the child fills, so a hand-written Then join does not either unless asked.

## Why a first plan that finished without filling cancels the child

A child that was never started would otherwise stay `pending` for ever and the plan would never be done. Marking it done as `cancelled` lets the parent end as `cancelled`.
