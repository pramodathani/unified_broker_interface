# Notes on `350_unified_order_execution_costs.sql`

The table holds one row per filled leg, written by `bin/unified/orders/execution_costs` through `ExecutionCostMeasurement.write`, which applies this file itself at the start of every write, in the same way the order engine applies `340_unified_synthetic_order_events.sql`. There is no other runner for it.

It sits in the ticks DDL directory beside the event log because both are order-engine tables in the `unified` schema, and `ExecutionCostMeasurement` reuses the event log's `DDL_DIRECTORY` constant rather than spelling the path out again.

## Chunks and compression

The engine sends hundreds of legs a day, not millions, so seven days to a chunk keeps chunks from being mostly overhead while still letting a "last N days" query exclude chunks. The table is not compressed: it is small, and rows of the last two days are deleted and rewritten every night.

## No primary key

A run deletes every row of the days it measures and inserts them again in one transaction, so a key is not needed to stop duplicates. A hypertable's unique index would also have to include `time`, which would not express "one row per leg" anyway.

## Column meanings

Every cost column is per unit and signed so that a positive number is money lost. `delay_cost + latency_cost + half_spread_cost + beyond_touch_cost = total_cost` whenever all three quotes were found. `total_cost_rupees` is empty outside the securities markets because the event log keeps the fill quantity as the broker reported it, which is lots at some brokers for currency and commodity contracts. `docs/architecture/execution-costs.md` has the full column list.

## The `price` column

`price`, the limit price a leg was sent with, was added on 2026-10-06 for the estimate check, which needs it to tell a leg that crossed the spread at its decision from one that rested. It is empty for a market order. Because the measurement rewrites whole days, the column was filled for the ten days already measured by re-running `bin/unified/orders/execution_costs --date 2026-10-06 --days 10`.
