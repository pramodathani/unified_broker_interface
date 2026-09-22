# Database

TimescaleDB, with one PostgreSQL schema per broker.

## One schema per broker

Zerodha's data lives in `zerodha.ticks`, `zerodha.order_updates`, `zerodha.instruments` and
`zerodha.price_history`. There is no table named `ticks_zerodha` in `public`.

The reason is operational. Each stream compresses, retains and drops independently; a broker
being re-ingested never locks another broker's chunks; and dropping a broker entirely is one
`DROP SCHEMA` rather than ten qualified deletes. Tables are named for their content, so the same
names appear in every schema that has the table and a query reads the same whichever broker it is against. Only the four brokers that stream positions have a `positions` table, and only the seven with price history a `price_history`.

### The one exception

The rule governs a broker's own observations. Data that belongs to no single broker sits in a schema of
its own, `unified`, starting with the tables of the
[instrument mapping](../guides/instrument-mapping.md) layer:

| Table | What it holds |
| --- | --- |
| `unified.instruments` | One row per real-world instrument, whoever lists it |
| `unified.broker_mappings` | The token each broker uses for that instrument, per day, and the extra attributes that broker's file publishes for it |
| `unified.contract_sizes` | Each live currency and commodity contract's lot size in quotation units, how it was decided and whether orders may be sent, per day |

`unified.broker_mappings` does carry a `broker` column, and that is its content rather than a
violation: the whole purpose of the row is to join a shared instrument to one broker's own
identifier for it. Putting the pair in any single broker's schema would make the other nine read
across a schema boundary to find them.

The tables built on that identity sit in the same schema for the same reason: they hold one instrument's
data whichever broker supplied it, each row naming the broker it came from. `unified.price_history`, with its
sources, corrections and adjustment factors, is the [unified price history](../guides/unified-price-history.md)
that `bin/unified/historical_prices` builds; `unified.ticks`, `unified.order_updates` and `unified.positions`
are written by the `bin/unified/persist_*` scripts. See [Unified scripts](../guides/unified-scripts.md#the-unified-schema).

## The four tables

=== "ticks"

    One row per [normalized tick](../architecture/contracts.md#the-tick), written by `bin/<broker>/persist_ticks`. Hypertable on `time`, chunked by day - a trading day's ticks for
    one broker sit in one chunk, which is the unit most queries scan and the unit compression and
    retention act on.

    The order book is stored as flattened numeric columns, `bid1_price` through `ask5_orders`,
    rather than as JSON. Timescale's columnar compression works on repeated numerics and barely
    helps JSON, and the common query - what was the touchline at time *t* - then needs no JSON
    operators.

=== "order_updates"

    One row per state transition, not one row per order, written by `bin/<broker>/persist_orders`. An
    append-only audit trail, so an order's whole history can be reconstructed. `raw` holds the broker's
    untouched payload.

=== "positions"

    One row per snapshot, written by `bin/<broker>/persist_positions` at the four brokers that stream
    positions. A position is state rather than an event, so the history is the series of snapshots
    rather than a series of changes.

=== "instruments"

    One row per contract per day, `download_date` being part of the key. Hypertable on
    `download_date`, chunked by month. Every column but `download_date`, a `DATE`, is `TEXT`, because the file is stored as the
    broker published it and typing happens on read.

## Compression and chunking

| Setting | Value | Applies to |
| --- | --- | --- |
| Chunk interval | 1 day | ticks, order_updates, positions |
| Chunk interval | 1 month | instruments |
| Compress after | 7 days | ticks, order_updates, positions |

Seven days keeps the current week uncompressed for fast ad hoc querying while everything behind
it shrinks.

## Querying

```sql
-- last trade for one instrument today
select time, last_price, volume
from zerodha.ticks
where id = 'NSE:INFY' and time >= current_date
order by time desc
limit 10;

-- one order's full history
select time, status, filled_quantity, average_price
from zerodha.order_updates
where order_id = '250912000123456'
order by time;

-- how many instruments each broker published today
select 'zerodha' as broker, count(*) from zerodha.instruments where download_date = current_date
union all
select 'dhan', count(*) from dhan.instruments where download_date = current_date;
```
