# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_order.py`

## `paper_filled` events

A paper `virtual_limit` order fills without a leg, so its fills are their own event, `paper_filled`, whose `filled_quantity` is the running total. `apply_paper_fill` copies it into `parameters['paper_filled']`, which is how the order knows after a restart how much it has already been filled. The event table has no constraint on event names, so no DDL changed.
