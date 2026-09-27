# Notes on `unified_broker_interface/utilities/order_engine/attached_hedge.py`

## Why the hedge grows by new orders rather than by modifies

`OneTriggersOther` grows its child with `reduce_leg` as the parent fills. A hedge is sized in whole lots of another instrument, so it changes in steps of a lot, and each step is sent as a new order for the lots still missing. No resting order is ever resized, which also keeps clear of `reduce_leg`'s handling of lot-based quantities.

## Why rounding is to the nearest lot

The Atlas says the hedge is "rounded to the lot size". Rounding down would leave a small position unhedged forever; rounding to the nearest keeps the hedge within half a lot of the target, over or under.

## Why delta is worked out at each fill

A delta changes with the underlying and with time, so the hedge for a later fill uses the delta at that moment. The interest rate is 0, as in the volatility order's default, because the hedge instrument is expected to be a future, which is already the forward.

## Why the forward and the hedge price use the hedge instrument's own tick

A parent that is not a market-watching type keeps no tick size, and the hedge instrument's tick often differs from the entry's (0.10 for a stock future against 0.05 for the stock). The forward is read, and the hedge priced, with the tick size the brokers agree on for the hedge instrument. The first version read both through the parent's view, and no hedge was ever sent, because there was no tick size to read a price with.
