# DDL and migrations

Schema definitions belong in `.sql` files, applied by a runner in filename order. SQL in a `.sql`
file is readable, diffable and reviewable as SQL - it highlights, it pastes into `psql`, and
adding a column produces a one-line diff. DDL assembled from Python string fragments can only be
reviewed by mentally executing the code that produces it, and it keeps the schema illegible to
anyone not reading the Python.

## How the runner works

```bash
python -m stock_brokers.instruments.sql.apply_ddl
```

[`apply_all`][stock_brokers.instruments.sql.apply_ddl.apply_all] globs `sql/ddl/*.sql`, sorts by
filename and executes each file. The numeric prefix decides order, so schemas exist before the
tables inside them:

```text
stock_brokers/instruments/sql/ddl/
├── 000_schemas.sql                     every broker's schema
├── 010_instruments_zerodha.sql
├── 020_instruments_dhan.sql
├── 030_instruments_groww.sql
├── 040_instruments_stoxkart.sql
├── 050_instruments_flattrade.sql
├── 060_instruments_fyers.sql
├── 070_instruments_kotak.sql
├── 080_instruments_shoonya.sql
├── 090_instruments_wisdom_capital.sql
└── 100_instruments_indmoney.sql
```

The whole run is one transaction: a broken definition rolls the batch back rather than leaving
the database half migrated.

## Four directories

Each subsystem keeps its own `sql/ddl` directory. The first three are applied whole by the single
[`apply_all`][stock_brokers.instruments.sql.apply_ddl.apply_all] above - the two thin entry points for the
mapping and historical directories import it rather than restating it - and the tick directory is applied a
file at a time, each file executed in one transaction by the script that needs it.

| Directory | Files | Applied by |
| --- | --- | --- |
| `stock_brokers/instruments/sql/ddl` | `000_schemas.sql`, `010` to `100` - the ten broker schemas and their `instruments` tables | `python -m stock_brokers.instruments.sql.apply_ddl` |
| `stock_brokers/instruments/mapping/utilities/sql/ddl` | `100_unified_schema.sql`, `110_unified_instruments.sql`, `120_unified_broker_mappings.sql` | `bin/unified/map_instruments` and `bin/unified/historical_prices` on every run, or `python -m stock_brokers.instruments.mapping.utilities.sql.apply_ddl` |
| `stock_brokers/instruments/historical/utilities/sql/ddl` | `000` to `060` - each broker's `price_history` and `price_history_progress`; `200` to `250` - the unified price history | `bin/unified/historical_prices` on every run, or `python -m stock_brokers.instruments.historical.utilities.sql.apply_ddl` |
| `stock_brokers/instruments/ticks/utilities/sql/ddl` | `010` to `100` - each broker's stream tables; `300` to `330` - `unified.ticks`, `unified.order_updates`, `unified.positions` and `unified.ticks_adjusted` | One file at a time, by the scripts that write the tables - see below |

The tick directory has no runner of its own, because no one step wants all of it: each
`bin/<broker>/persist_*` script applies its broker's `<NNN>_<broker>_streams.sql` when it starts,
`bin/unified/persist_ticks`, `persist_orders` and `persist_positions` apply `300`, `310` and `320`, and
`bin/unified/historical_prices` applies `300` and `330` after the price DDL, because the adjusted view reads
`unified.adjustment_ranges`.

Order matters once, on a fresh database. The per-broker price tables live in the broker schemas `000_schemas.sql`
creates, so the instrument runner goes first. The unified price tables refer to `unified.instruments`, so the
mapping directory has to have run before `200` to `250` - `bin/unified/historical_prices` applies the two in that
order. The stream files create their own broker schema, and so depend on nothing.

The historical directory numbers the per-broker tables from 000 and the unified ones from 200:

```text
stock_brokers/instruments/historical/utilities/sql/ddl/
├── 000_price_history_zerodha.sql … 060_price_history_wisdom_capital.sql
├── 200_unified_price_history.sql               every instrument's bars, under its unified id
├── 210_unified_price_history_sources.sql       which broker series feeds which instrument
├── 220_unified_adjustment_factors.sql          splits, bonuses and demergers
├── 230_unified_yahoo_fetch_state.sql           where the Yahoo Finance fetch has got to
├── 240_unified_price_history_adjusted.sql      the adjusted views and adjusted_bars()
└── 250_unified_price_history_corrections.sql   undoing adjustments a broker already applied
```

The runner executes a file as one batch inside one transaction, so a file must not hold anything
PostgreSQL refuses to run in a transaction - no continuous aggregates, no `CREATE INDEX
CONCURRENTLY`. Views and functions use `CREATE OR REPLACE`, which keeps them re-runnable.

Within the mapping directory the prefixes carry a hard dependency of their own, since
`unified.broker_mappings` has a foreign key to `unified.instruments`:

```text
stock_brokers/instruments/mapping/utilities/sql/ddl/
├── 100_unified_schema.sql              the schema for data that belongs to no single broker
├── 110_unified_instruments.sql         one row per real-world instrument
└── 120_unified_broker_mappings.sql     each broker's token for it, per day
```

## Every statement is re-runnable

This is what makes the runner both the creation step and the migration step. There is no separate
migration tool and no version table - a definition changes, the file changes, the runner runs
again.

```sql
CREATE SCHEMA IF NOT EXISTS zerodha;

CREATE TABLE IF NOT EXISTS zerodha.instruments (
    "instrument_token" TEXT,
    "tradingsymbol"    TEXT,
    "download_date"    DATE NOT NULL
);

SELECT create_hypertable(
    'zerodha.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
```

## Adding a column

Append an `ALTER TABLE … ADD COLUMN IF NOT EXISTS` to the broker's existing file rather than
creating a new one, so the file stays the single description of that table, and re-run the
runner. The instrument ingester raises when a downloaded file carries a column the table does not
have, naming the column - which is usually how you find out one is needed.

!!! note "Each broker's stream tables"

    `stock_brokers/instruments/ticks/utilities/sql/ddl/010_zerodha_streams.sql` to
    `100_stoxkart_streams.sql` define every broker's `ticks` and `order_updates`,
    and, for Fyers, Groww, Kotak and Wisdom Capital, `positions` - schema, table, hypertable, index and compression - and each
    `bin/<broker>/persist_*` script applies its broker's file when it starts. The persisters name their columns
    in `COPY`, so they depend on the columns existing, not on their order.
