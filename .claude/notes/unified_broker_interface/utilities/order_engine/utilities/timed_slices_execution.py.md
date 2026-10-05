# Notes on `unified_broker_interface/utilities/order_engine/utilities/timed_slices_execution.py`

## Why there is a base class here

TWAP, VWAP and front-loaded share everything but their weights: the interval `over_minutes × 60 / slices`, the first slice at once, one slice per tick, the largest-remainder split and the last slice taking what is left. That is genuinely identical mechanism, so it lives in one shallow base class and each subclass keeps only `slice_weights`, as `twap.py`, `vwap.py` and `implementation_shortfall.py` do today.

## Why the slice number is the count of the part's own legs

Today's TWAP counts every leg of the parent, which breaks the moment another part shares the parent. Counting this part's legs keeps the schedule right inside a join and after a restart; only `started_at` is kept in memory, written with a recorded event when the schedule begins.

## Why each slice is sized from the total when it falls due

A join can change the order's total while the schedule runs, for example a bracket's entry growing. Sizing slice `i` from the total at that moment spreads the change over the slices still to come, and the last slice sends whatever is left, so the slices always add up to the total. If every slice has gone before the total grows, the growth is not sent; lifetimes and Repeat in later stages are the place to handle that.

## `until` (2026-10-01)

Today's closing price order works out its VWAP's length from the window's end and the moment it starts, whether that is the window's opening or a moment inside it. `until` is that rule for any timed execution: `begin` keeps the minutes in memory, recorded with the order, and `interval` reads them from there. It is set by the reader after building the execution rather than passed to every subclass's constructor.

## Empty slices and lots (2026-10-05)

The slice to send next used to be the number of broker orders placed, and a slice that worked out to nothing returned no piece, so the count never moved past it: a closing_price order of 3 sent nothing at all, one of 5 stopped after 2, and a vwap of 10 in 10 slices stopped after 6. `slices_done` in memory now counts slices sent or skipped; an empty slice is counted and skipped. It is written with the event of every slice sent, and a missing value falls back to the broker order count, so a restart recomputes any skips after the last slice. Slices are also shared out in whole lots (`shared_lots`), since a 150-unit slice of a 100-unit crude oil lot was refused. Slices still go out after the market's close; that is documented rather than changed.
