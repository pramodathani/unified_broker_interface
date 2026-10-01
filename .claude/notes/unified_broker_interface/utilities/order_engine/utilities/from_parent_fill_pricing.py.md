# Notes on `unified_broker_interface/utilities/order_engine/utilities/from_parent_fill_pricing.py`

## Where the first leg's fills come from

The pricing reads the parent's legs whose role is the Then join's first order's path, which the plan reader sets when it reads the join. Today's legged spread prices each top-up from the worked leg's cumulative average price, and averaging over the first order's legs weighted by fill gives the same number when the first order is one broker order. The price is not rounded onto the tick, as today's is not.
