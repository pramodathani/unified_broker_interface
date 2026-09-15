# Notes on `stock_brokers/instruments/ticks/utilities/sql/ddl/100_stoxkart_streams.sql`

## What the file creates

The file creates the `stoxkart` schema and one table, `stoxkart.ticks`, as a TimescaleDB hypertable. `bin/stoxkart/persist_ticks` applies it every time it starts, draining `stoxkart:quotes:stream` into the table, so a new database needs no separate step. Every statement is safe to run again.

## Why there is no `order_updates` or `positions` table

The other brokers' stream files also create `<broker>.order_updates`, and four of them `<broker>.positions`, because those brokers stream order and position updates over a websocket. Stoxkart's API streams neither. It delivers order status only to a postback URL registered on the API app, which needs a public web server. With no stream there is no persister and nothing to store, so the tables were left out rather than created empty.

## Why the table matches the other brokers' tick tables

The columns, the one-day chunks, the `(id, time DESC)` index, compression segmented by `id` and the seven-day columnstore policy are copied from `010_zerodha_streams.sql`. One table per broker keeps each stream compressing, retaining and reloading on its own. The order book is flattened into five bid and five ask levels of numeric columns, because columnar compression works on repeated numerics and barely helps JSON.

## Why the file has no comments

The other stream files explain themselves in SQL comments. This one follows the user's rule that explanations go in a sidecar note, so the same reasoning is here instead.
