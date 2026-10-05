# Notes on `unified_broker_interface/utilities/order_engine/utilities/from_parent_fill_pricing.py`

## Where the first leg's fills come from

The pricing reads the parent's legs whose role is the Then join's first order's path, which the plan reader sets when it reads the join. Today's legged spread prices each top-up from the worked leg's cumulative average price, and averaging over the first order's legs weighted by fill gives the same number when the first order is one broker order. The price is not rounded onto the tick, as today's is not.

## Each order keeps the net, on the tick (2026-10-05)

Each new order is priced from `sent_before`, the second leg's earlier orders, so the leg as a whole averages the price the net needs. Every top-up used to be priced from the first leg's cumulative average alone, so earlier orders priced from an earlier average left the net at 20.65 against 20 in one run. The price is rounded to the order's tick, down for a buy and up for a sell, so the net is the one asked for or better; 982.05 on a future with a tick of 0.10 was refused by the broker, and the refusal was swallowed, leaving the parent working with nothing hedged. `own_path` is set by the plan reader beside `first_path`.
