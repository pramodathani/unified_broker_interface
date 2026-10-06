# Notes on `estimate_check.py`

## What is compared with what

The estimate is the cost of crossing at the decision moment's book, against that book's mid-price. The measured figure it is compared with is `half_spread_cost + beyond_touch_cost`, which is measured against the mid-price when the broker answered. Both leave out the price moving between decision and answer (`delay_cost` and `latency_cost`), which the estimate does not try to predict. The estimate uses the filled quantity, so a partly filled leg is compared on what actually filled.

## Crossing and resting

The first run on 2026-10-06 treated a stop order whose trigger price was through the book as crossing. Those stops produced the largest errors (up to 400 basis points), because a stop fills later, after its trigger, against a book the decision never saw. Stops are therefore always resting. After that change the crossing legs averaged 6.11 estimated against 5.81 measured basis points.

A limit leg whose book is missing at the decision counts as resting, because it cannot be shown to have crossed; a market leg with no book stays crossing but has no estimate.

## Speed

On 2026-10-06 the check of 455 legs took about 0.9 seconds: one book query per leg on the `(instrument_id, time DESC)` index, and one daily bar query per instrument and day thanks to `liquidity_cache`.
