# Notes on `unified_broker_interface/utilities/order_engine/utilities/iceberg_execution.py`

## Why it copies the iceberg type's rules

The piece size, the variation seeded from `parent_order_id` and the piece count (`zlib.crc32`, `seed % 2001`), and the rule that a cancelled or rejected piece stops the iceberg are those of `iceberg.py`, so the `iceberg` preset sends what today's type sends. The piece count is now this part's own legs rather than all of the parent's, which is the ownership rule that lets an iceberg sit inside a bracket.
