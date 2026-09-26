# Notes on `unified_broker_interface/utilities/broker_orders/utilities/prepared_modification.py`

## Why this class exists

It holds one modification that has passed every check, with its built request, so that the single form of `PUT /api/orders/modify` and each order of a list answer through the same `dry_run_answer` and `send`. The reasoning is the same as for `PreparedCancel`, whose note explains why the two are separate classes rather than one with a flag.

`instrument_id` is carried because the answer reports it, and it is None when the order's instrument could not be found in today's catalogue. A price-only change still goes ahead in that case, and only the tick check is skipped.
