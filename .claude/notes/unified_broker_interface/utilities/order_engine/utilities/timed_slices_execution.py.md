# Notes on `unified_broker_interface/utilities/order_engine/utilities/timed_slices_execution.py`

## Why there is a base class here

TWAP, VWAP and front-loaded share everything but their weights: the interval `over_minutes × 60 / slices`, the first slice at once, one slice per tick, the largest-remainder split and the last slice taking what is left. That is genuinely identical mechanism, so it lives in one shallow base class and each subclass keeps only `slice_weights`, as `twap.py`, `vwap.py` and `implementation_shortfall.py` do today.

## Why the slice number is the count of the part's own legs

Today's TWAP counts every leg of the parent, which breaks the moment another part shares the parent. Counting this part's legs keeps the schedule right inside a join and after a restart; only `started_at` is kept in memory, written with a recorded event when the schedule begins.

## Why each slice is sized from the total when it falls due

A join can change the order's total while the schedule runs, for example a bracket's entry growing. Sizing slice `i` from the total at that moment spreads the change over the slices still to come, and the last slice sends whatever is left, so the slices always add up to the total. If every slice has gone before the total grows, the growth is not sent; lifetimes and Repeat in later stages are the place to handle that.
