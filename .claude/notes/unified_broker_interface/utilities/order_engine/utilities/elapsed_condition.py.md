# Notes on `unified_broker_interface/utilities/order_engine/utilities/elapsed_condition.py`

## Why it is not a trigger a caller writes

The reader builds it only for a Repeat join's copies. A caller wanting an order some minutes after placing can use a Repeat of one, or a `time_at`. Keeping it out of the trigger slot means the trigger vocabulary stays the design's.
