# Notes on `latency_calibration.py`

## Categories

`category` repeats the lowest-cost selector's rule (`LowestCostSelector.category`) from what the cost table stores: a segment whose shape in `TradeableSegments.SHAPES` is a future or option is `fno`, then `CNC` is `delivery`, and anything else is `intraday`. The selector reads `instrument.kind() == 'derivative'`, which is the same thing worked out from the live instrument. Keeping the categories identical is what lets the selector add these figures to `fee(category)` later without translating.

## Writing

The update follows `MarginCalibration.write`: `COALESCE(%s, column)` so an unmeasured figure keeps what the table held, and `latency_calibrated_at = now()` only for brokers that had something measured. A broker with measured legs but no row in `unified.broker_order_costs` is logged as a warning rather than inserted, because a row there also carries brokerage and limits that someone has to decide.

## Window

`WINDOW_DAYS = 20` is about a month of trading days: long enough for most brokers to reach 30 legs per category at the volumes seen in late September 2026, short enough that a broker's change of infrastructure shows within a month.
