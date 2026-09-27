# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_order.py`

## `paper_filled` events

A paper `virtual_limit` order fills without a leg, so its fills are their own event, `paper_filled`, whose `filled_quantity` is the running total. `apply_paper_fill` copies it into `parameters['paper_filled']`, which is how the order knows after a restart how much it has already been filled. The event table has no constraint on event names, so no DDL changed.

## Why `parameters_changed` exists

A type's parameters were recorded once, with `parent_received`, and every later change to them, such as a trailing stop's watermark, lived only in the Redis cache and was lost when recovery rebuilt the parent from the record. For a watermark that was harmless, because the stop only ratchets. For the re-anchoring a caller's modify now causes, it was not: a peg would snap back to its old offset after a restart. `parameters_changed` carries the whole of `parameters` as they became, and `apply_parameters` replays it.
