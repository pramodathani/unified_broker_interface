# Notes on `stock_brokers/instruments/mapping/utilities/sql/ddl/150_unified_broker_order_costs.sql`

`unified.broker_order_costs` holds one row per broker: the order messages it allows per second, minute, hour and day, and the brokerage it charges for one delivery, F&O and intraday order. The column names are the ones the user gave in the table they supplied on 2026-09-29, and the seed rows are that table's values, with the brokers renamed to the names the code uses (`kotak` for Kotak Neo, `shoonya` for Shoonya (Finvasia)).

It is an ordinary table, not a hypertable, because it has ten rows that change a few times a year.

A limit may be `NULL`, which means the broker sets no limit for that window. The `CHECK` constraints refuse zero and negative limits and negative fees, so a mistyped value is rejected when it is written rather than discovered when orders are routed by it.

The seed uses `ON CONFLICT (broker) DO NOTHING`. This file runs before every daily mapping run, and the rows are meant to be edited by hand afterwards; a seed that updated on conflict would overwrite those edits every morning.

The file lives with the mapping DDL because that is the runner for the `unified` schema's ordinary tables and it runs daily, so the table exists on any database the mapping has run against.
