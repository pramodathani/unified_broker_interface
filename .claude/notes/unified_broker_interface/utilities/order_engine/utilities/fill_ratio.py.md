# Notes on `unified_broker_interface/utilities/order_engine/utilities/fill_ratio.py`

## Whole lots and the broker

Today's hedge rounds `ratio × filled` half up to whole lots of the hedge instrument at the entry's broker, and sends nothing until a lot is missing. The lot is read at the plan's chosen broker, which is the entry's, from the catalogue's handle. `OrderPart.start` keeps a part pending, rather than done, while the scaled size is zero, so the Then join starts it again on the next fill.

## Not built

The design's `parent_fill_delta` sizes a hedge by an option's Black-76 delta at a volatility. It needs the option model at each fill; the `attached_hedge` preset refuses `delta_volatility` as not built.

## parent_fill_delta is built (2026-10-05)

The entry above is out of date: `FillDelta` sizes a hedge by the option's delta, and the `attached_hedge` preset accepts `delta_volatility`.
