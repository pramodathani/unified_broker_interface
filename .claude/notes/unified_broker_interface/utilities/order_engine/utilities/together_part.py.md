# Notes on `unified_broker_interface/utilities/order_engine/utilities/together_part.py`

## Why `same_broker` is not a setting

The design lists `same_broker`. Every broker order of one plan already goes to the broker the first one chose, through `PlanOrder.chosen_broker`, so every together join is pinned to one broker; spreading a group across brokers is not built.

## How the group's margin is checked

Today's basket hands every leg to the placement of the first, so the lowest-cost selector checks the whole basket's margin. A plan's orders are placed by their own parts, so the join builds the group with `group_legs` and leaves it on `PlanOrder.group_margin_legs` while its children start; `OrderPart.place` passes it on only while no broker has been chosen, which is the first placement. `group_legs` prices each order to build the group, so an order's pricing memory is recorded twice when a group is placed; it is the same memory.

## Why the parent can end `completed` for orders on different instruments

`traded` adds quantities across instruments, which means nothing as a number, but it is only used to tell whether anything traded; a together join is never sized by a Then join, which the reader refuses.
