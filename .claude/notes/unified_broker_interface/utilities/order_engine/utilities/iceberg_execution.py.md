# Notes on `unified_broker_interface/utilities/order_engine/utilities/iceberg_execution.py`

## Why it copies the iceberg type's rules

The piece size, the variation seeded from `parent_order_id` and the piece count (`zlib.crc32`, `seed % 2001`), and the rule that a cancelled or rejected piece stops the iceberg are those of `iceberg.py`, so the `iceberg` preset sends what today's type sends. The piece count is now this part's own legs rather than all of the parent's, which is the ownership rule that lets an iceberg sit inside a bracket.

## Randomised slices in lots (2026-10-05)

`piece_size` brings a randomised size to the nearest whole number of lots, at least one. A NIFTY option at lot 75 with slices of 150 varied by 1% gave 151; the broker refused it, the follower logged the refusal, and the iceberg stopped with 600 of 750 never sent and nothing resting. A fixed slice size is not rounded, so a slice that is not whole lots is still refused when the order arrives.
