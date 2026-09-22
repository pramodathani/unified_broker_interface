# Notes on `stock_brokers/instruments/ticks/utilities/sql/ddl/100_stoxkart_streams.sql`

## What the file creates

The file creates the `stoxkart` schema and two tables as TimescaleDB hypertables: `stoxkart.ticks`, which `bin/stoxkart/instruments/store_quotes_to_db` fills from `stoxkart:quotes:stream`, and `stoxkart.order_updates`, which `bin/stoxkart/orders/store_orders_to_db` fills from `stoxkart:order-updates:stream`. Each persister applies the file every time it starts, so a new database needs no separate step. Every statement is safe to run again.

## Why there is no `positions` table

Four other brokers' stream files also create `<broker>.positions`, because those brokers stream position updates. Stoxkart's order socket carries order updates only, so there is no position stream to persist. The first version of this file had no `order_updates` table either, because Stoxkart's order socket had not been found yet; it was appended the same day.

## Why the table matches the other brokers' tick tables

The columns, the one-day chunks, the indexes, compression segmented by `id` or `order_id` and the seven-day columnstore policy are copied from `010_zerodha_streams.sql`. One table per broker keeps each stream compressing, retaining and reloading on its own. The order book is flattened into five bid and five ask levels of numeric columns, because columnar compression works on repeated numerics and barely helps JSON.

## Why the file has no comments

The other stream files explain themselves in SQL comments. This one follows the user's rule that explanations go in a sidecar note, so the same reasoning is here instead.
