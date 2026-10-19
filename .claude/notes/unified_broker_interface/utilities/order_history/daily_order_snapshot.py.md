# daily_order_snapshot.py

Added on 2026-10-20. Flattrade permits one websocket per session and the quote feed holds it, so its order updates socket is not run and `flattrade:order-updates:stream` is never written; its orders exist only in `flattrade:orders:orders`, which the poller fills and which expires at 06:00 IST. Nothing kept them, so the stop slippage measurement could not price a stop the strategy cancelled just as it filled.

## Why the combined document, not each broker's hash

`unified:orders:orders` is every broker's orders already normalized to the REST order contract, resolved to an `instrument_id`, and carrying `engine_parent_id`, `leg_role`, `intent_id` and `synthetic_type`, which is what joins a broker order back to the engine parent. Reading it means no per-broker parsing here.

## Why INSERT and not COPY

The day is a few hundred rows, and parameters need no escaping. The COPY writers in `bin/*/store_*_to_db` were stuck for three weeks on one unescaped carriage return (fixed by #83); this table cannot fail that way.

## Choices

- The day is the order's `order_timestamp` date in India, and by default every day the document holds is saved, so a run after midnight still saves the evening's day.
- The day's rows are deleted before inserting, so an order that changed state after an earlier save is stored as it ended.
- A missing document exits 0 with a warning, so `stop_slippage`, which runs after it in the same oneshot unit, is not skipped.
- It is a plain table, not a hypertable, keyed by day, broker and order id.

Checked on 2026-10-20 00:01: 366 Flattrade orders of 2026-10-19 saved, 356 filled, worth 40,98,623.75, the same turnover as Flattrade's bill FO20261019.
