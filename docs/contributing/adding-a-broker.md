# Adding a broker

The base classes are built so that each new broker is only the part that is genuinely
broker-specific, and the scripts are built so that each one is complete on its own. Work through
the steps in this order - each is useful on its own, and the earlier ones are what the later ones
need.

## 1. The API class

Create `stock_brokers/api/<broker>.py` with a `BrokerAPIException` subclass and a `BrokerAPI`
subclass. Implement `__init__` (the login flow) and `_request`; `get`, `post`, `put`, `patch` and
`delete` come from the base.

Write the whole login inside `__init__`, from the stored-token check to the token write, rather than
splitting it into private helper methods, so that every broker's login reads from top to bottom in one
place. Some repetition between login steps is acceptable. Add another method only when code outside the
class calls it, as the Kotak scripts call [`KotakAPI.url`][stock_brokers.api.kotak.KotakAPI.url] to build
URLs on the host that Kotak assigned to the session.

Follow the pattern of trying an authenticated call first and only logging in when it fails, so
constructing the object is cheap while a token from earlier in the day is still valid. On a
successful login, upsert `last_login` in MongoDB and mirror it into the Redis `last_login` hash. Append a
request to the Redis list `broker_api_calls` only when called with `verbose`, as every other broker does:
an unconditional append grows without bound and carries the access token.

Add the broker's document to the `settings` collection with whatever credentials its flow needs.

## 2. Instruments

Create `stock_brokers/instruments/<broker>.py`:

```python
class NewBrokerInstruments(BrokerInstruments):
    BROKER_NAME = "new_broker"
    DEDUPE_KEY_COLUMNS = ["instrument_token"]
    DEDUPE_SORT_COLUMN = None

    def download(self):
        return pandas.read_csv(INSTRUMENTS_URL, dtype=str)
```

Then:

- add a `CREATE SCHEMA IF NOT EXISTS <broker>;` line to `sql/ddl/000_schemas.sql`
- add a numbered `sql/ddl/<n>_instruments_<broker>.sql` defining the table and its hypertable
- register the class in `INGESTERS` in `orchestrator.py`
- run the DDL runner, then ingest once with `--bootstrap` to see the real columns

Read the file as text throughout. Let an unknown column raise; add it to the DDL rather than
dropping it.

### 2b. Mapping the instruments

A raw table on its own cannot be joined to any other broker's. To bring the new broker into
`unified.instruments` and `unified.broker_mappings`, add two more files:

- `stock_brokers/instruments/mapping/utilities/rules/<broker>.yaml`, declaring the broker's
  segments in canonical order with their `match` rules, `identity` and `broker_fields`. Its
  `raw_table:` is `<broker>.instruments`.
- `stock_brokers/instruments/mapping/<broker>.py`, a `BrokerMappingAdapter` subclass. It may be
  nothing but `BROKER_NAME` if equality rules can express the broker's file; override `classify`,
  `to_identity` or `read_raw_rows` only where they cannot.

Then register the adapter in `ADAPTERS` in `mapping/utilities/orchestrator.py`, and add the broker
to `MAPPED_BROKERS` in `mapping/utilities/segments.py` - **at the right position**, not the end.
That list is the processing order, and a broker that reads index names through
`equity_index_lookup` has to run after the brokers that write them.

Check the run with `matched + uncategorised == raw_rows` and no row errors, then confirm the new
broker converges onto existing instruments rather than creating its own. See
[instrument mapping](../guides/instrument-mapping.md).

## 3. Price history

If the broker serves candles, create `stock_brokers/instruments/historical/<broker>.py` with a
`BrokerCandles` subclass - six class attributes, `fetch_candles` and `parse_response` - add a
numbered `.sql` file for its `price_history` and `price_history_progress` tables to
`stock_brokers/instruments/historical/utilities/sql/ddl/`, and register it in `DOWNLOADERS`. If it does not,
record why in `UNSUPPORTED`. [Price history](../guides/price-history.md#adding-a-broker) has the shape and
the four things that decide whether it works.

Verify it on a handful of hand-seeded series before seeding the whole instrument master; a broker
is a million series and up, and a walk that repeats one window is much cheaper to notice early.

## 4. The broker's scripts

Create `bin/<broker>/`, one self-contained script per job, each starting with the `run_under_venv`
bootstrap and carrying a module docstring that is its full reference. The existing brokers' directories are
the pattern; take the script from the broker on the same platform where there is one. For the two websocket
scripts, follow Zerodha's, whose sockets are in `stock_brokers/websockets/zerodha.py`, and add the broker's
cases to `test_runs/websocket_feeds/`.

| Script | What it needs from the broker |
| --- | --- |
| `session/connect`, `session/disconnect` | The API class; `connect` writes `<broker>:session:status` |
| `user/details`, `orders/api_order_details`, `orders/api_trade_details`, `portfolio/holdings`, `portfolio/positions`, `portfolio/funds` | Each endpoint, and how the broker signals a dead session, so the poller logs in again **before** its next request |
| `instruments/websocket_quotes` | A quotes socket in `stock_brokers/websockets/<broker>.py` - a `BrokerWebsocket` subclass with the feed's connection, subscription and decoding, producing the [normalized tick](../architecture/contracts.md#the-tick) and handing it to a callback - and a script that chooses the instruments and writes the ticks to Redis |
| `orders/websocket_order_details` | An order updates socket in the same module, which picks the broker's order messages out of the feed and hands them to a callback, and a script that turns them into the [normalized order](../architecture/contracts.md#the-order), and positions where the broker streams them, and merges them into Redis |
| `instruments/store_quotes_to_db`, `orders/store_orders_to_db`, `portfolio/store_positions_to_db` | Only the column mapping; `store_positions_to_db` only if the broker streams positions |
| `instruments/daily_feed` | Runs the ingester from step 2 and writes `<broker>:instruments:master` |
| `instruments/price_history` | Wraps the `BrokerCandles` subclass from step 3, logging in through the API class |

Map the broker's status, product, order type and validity spellings onto the
[shared vocabulary](../architecture/contracts.md#the-shared-vocabulary), adding them to the script's tables
rather than branching in the parser, and keep the broker's own row as `data`.

## 5. The stream tables

Add `stock_brokers/instruments/ticks/utilities/sql/ddl/<NNN>_<broker>_streams.sql`, numbered after
`100_stoxkart_streams.sql`, holding the broker's schema, `ticks`,
`order_updates` and, if it streams them, `positions` - table, hypertable, indexes and compression, every
statement safe to run again. Each `store_*_to_db` script applies this file by name when it starts, so there is no
separate step. See [DDL and migrations](../database/ddl.md).

## 6. The units

Create `services/<broker>/` with a template per folder - `<broker>-instruments@.service`,
`<broker>-orders@.service`, `<broker>-portfolio@.service` and `<broker>-user@.service` - plus
`<broker>-login.service`, `<broker>-login.timer`,
`<broker>-historical-prices.service` if it serves candles, and `<broker>.target`, whose header comment
carries the install commands. Add its `bin/<broker>/instruments/daily_feed` line to `unified-mapping.service`.
See [Running it as a service](../guides/services.md).

## 7. The unified scripts

The `bin/unified/` scripts pick a broker up only once it is in their lists: `BROKERS` in each combiner and
in `websocket_quotes`, `ORDER_BROKERS` and, if it streams positions, `POSITION_BROKERS` in
`websocket_order_details`. Each combiner also has a per-broker field table it reads that broker's data
with, and `websocket_quotes` carries its own normalizer per broker in `build_normalizers`, stating which quantities it reports in lots, when its `close`
is the previous close and which timestamps are true. See [Unified scripts](../guides/unified-scripts.md).

## 8. The REST API

- Add the API class to `API_CLASSES`, and its login unit to `LOGIN_UNITS`, in
  `unified_broker_interface/utilities/broker_quotes/utilities/clients.py`.
- If the API should fetch quotes from the broker when the quote cache cannot answer, a `TickNormalizer` in
  `stock_brokers/instruments/ticks/<broker>.py` - its `feed_key`, lot fields, close policy and trusted
  timestamps - registered in `NORMALIZERS` in `ticks/utilities/registry.py` and placed in the priority order
  in `ticks/utilities/sources.py`; then `broker_quotes/<broker>.py`, added to `SOURCES` only once its quotes
  have been checked against live quotes and against Zerodha on the same instruments.
- For placing, modifying and cancelling orders, `unified_broker_interface/utilities/broker_orders/<broker>.py` with a
  [`BrokerOrders`][unified_broker_interface.utilities.broker_orders.base.BrokerOrders] subclass: its
  `MARKETS` with each market's exchange or segment code, the settings each request needs, its place,
  modify and cancel requests with the fields its modify request can change, and how it reads a success
  answer. If the broker's order book stores a bare exchange such as `NSE` rather than the market code, it
  also overrides `stored_exchange_matches`. Add it to `BROKER_ORDER_CLASSES` in
  `broker_orders/utilities/registry.py`, whose order is the round robin's turn order, and add a dry run and
  a sent order for it to `test_runs/order_routes.py` before recording. List a market only once the broker's
  order API has been confirmed to take it, and give every currency or commodity market an entry in
  `QUANTITY_UNITS` saying how the broker counts quantity there (`lots`, `units` or `broker_lot_size`); a
  currency or commodity market without one passes the broker over.
- If the broker appears in the `broker_details` export, add its display name to `BROKER_CODES` in
  `unified_broker_interface/utilities/import_details.py`, which stops the import on a display name it does not know.

## 9. Documentation

Add the broker to [the coverage matrix](../brokers/coverage.md), to the per-broker notes on
[Brokers](../brokers/index.md), especially anything surprising about its login or protocol, and to the
tables in [Broker scripts](../guides/broker-scripts.md). The API reference picks up new modules on its own.

Read [Pitfalls](pitfalls.md) before starting rather than after finishing. Most of what is on that
page is a broker behaving in a way that reads as something else entirely, and every entry cost a
day to find the first time.

## Validate one broker end to end first

When rolling out a new pattern across the ten brokers, take one broker all the way through
against the live broker before replicating. A design that looks right in nine near-identical
copies is nine times the rework when the live feed disagrees with it.
