# Notes on `stock_brokers/instruments/ticks/utilities/sql/ddl/340_unified_synthetic_order_events.sql`

## Why the table is here rather than under the order engine

The build plan put this file in a new `sql/ddl/` directory inside the order engine's own package, with its own runner. That is not how this repository handles a table fed by a Redis stream. `unified.order_updates` and `unified.positions` live in this directory, the directory deliberately has no runner, and the one script that writes each table applies its own file when it starts. The engine does the same, so there is one convention rather than two.

`340` is the next free number after the `300` to `330` block of unified tables here.

## Why there is no primary key

Two reasons, and the second is the one that matters on the order path.

A hypertable's unique index has to include the partitioning column, so `UNIQUE (parent_order_id, sequence)` is not available at all. Adding `"time"` to it would be accepted but would not give the guarantee wanted, since the same sequence written twice at different instants would satisfy it.

More importantly, a duplicate row here is harmless and a rejected insert is not. Recovery folds events by `(parent_order_id, sequence)` and keeps the first, so writing the same transition twice changes nothing. A unique violation, by contrast, would raise on the order path at the exact moment the engine is trying to record that it is about to send an order, which is the worst possible time to fail.

## Why a day to a chunk

`unified.order_updates` uses a month, because it holds a few hundred sparse rows a day and monthly chunks keep them from being mostly overhead.

This table is denser: every parent writes a row per transition, and a chaser re-pricing through the afternoon writes many. More to the point, the query that matters is recovery, which reads every row since the last 06:00 IST. A day to a chunk keeps that scan inside one or two chunks. The columnstore policy then compresses anything older than a week, by which time the rows are only of historical interest.

## What `detail` is for on a `leg_requested` row

It holds the request as a dry run would show it: method, URL and body, with the credentials left out. That is not for diagnosis, although it serves that too.

It is what the orphan matcher reads. When an engine dies between sending a child order and recording the broker's answer, the only evidence that an order may exist is this row, and matching it against the broker's own order book means comparing the quantity, price, side, product and tag that actually went out — not what the caller asked for, which may differ after unit conversion into the broker's own lots.
