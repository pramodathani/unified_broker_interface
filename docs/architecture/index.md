# Architecture

The project is two layers of scripts and a REST API over one set of shared stores, built on the packages
in `stock_brokers`. The layers are deliberately independent: each broker's scripts run without any other
broker's, every script does one thing and needs no other process running, the unified scripts read only
Redis and the database and never call a broker, and a broker missing from one part does not hold up the
others.

| Layer | Where | What it does |
| --- | --- | --- |
| Broker scripts | `bin/<broker>/` | The only code that talks to a broker: sessions, pollers, quote and order update feeds, persisters, instrument masters and candles. See [Broker scripts](../guides/broker-scripts.md) |
| Unified scripts | `bin/unified/` | Every broker combined from Redis and the database: instruments, price history, quotes, orders and the portfolio. See [Unified scripts](../guides/unified-scripts.md) |
| REST API | `unified_broker_interface` | One HTTP interface over the unified layer, and order placement at a broker. See [REST API](../guides/rest-api.md) |
| Services | `services/<broker>/`, `services/unified/` | The systemd user units that run all of it. See [Running it as a service](../guides/services.md) |

## Package layout

```text
bin/
├── <broker>/                 self-contained scripts: login, pollers, feeds, persisters, instruments, history
├── unified/                  scripts that combine every broker from Redis and the database
└── rest-api, rest-api-app, search-instruments, zerodha-quote, check-broker-connections, import-api-details
services/
├── <broker>/                 the systemd user units that run bin/<broker>/
└── unified/                  the units that run bin/unified/ and the REST API

stock_brokers/
├── api/                      REST: login, then authenticated requests
│   ├── base.py               BrokerAPI, BrokerAPIException
│   ├── session.py            ensure_session: log in once, safely, from any process
│   └── <broker>.py           one per broker
└── instruments/              daily instrument masters
    ├── base.py               BrokerInstruments: clean, dedupe, write
    ├── orchestrator.py       run every broker, one try/except each
    ├── sql/apply_ddl.py      the DDL runner
    ├── sql/ddl/*.sql         schemas and instrument tables
    ├── <broker>.py           one per broker: where the file is, what shape it arrives in
    ├── mapping/              every broker's instruments onto unified.instruments and unified.broker_mappings
    │   ├── base.py           BrokerMappingAdapter: rules, identity, the database writes
    │   ├── <broker>.py       one per broker: only what its rules file cannot express
    │   └── utilities/        rules files, orchestrator, cache, resolution, collisions, and the mapping DDL
    ├── historical/           historical candles into <broker>.price_history
    │   ├── base.py           BrokerCandles: the queue, rate limiter, watermarks
    │   ├── noren.py          the platform Flattrade and Shoonya share
    │   ├── <broker>.py       one per broker: endpoint, intervals, window caps
    │   └── utilities/        the registry, the unified price history, and the price history DDL and its runner
    └── ticks/                what each broker's tick values mean, for the REST API's broker quotes
        ├── base.py           TickNormalizer: token segments, lots, close, timestamps
        ├── <broker>.py       one per broker
        └── utilities/        pipeline, registry, resolution, sessions and calendars, sources, and the stream DDL

unified_broker_interface/     the REST API
├── api.py, wsgi.py           the Flask application and the gunicorn entry point
├── blueprints/               one module per group of endpoints
└── utilities/                the token store, instrument lookups, and per-broker funds, holdings, orders,
                              positions and quote modules

utilities/
├── configurations.py         the environment, and the clients built from it
├── bootstrap.py              runs a bin/ script under the virtual environment
├── poll_reporter.py          PollReporter: one journal line per change, not per cycle
└── gen_ref_pages.py          builds the API reference pages during a docs build

test_runs/                    manual scripts: offline suites, the REST API test page, a live login check
```

## What lives beside the broker modules

A package that implements something once per broker holds exactly three kinds of file:
`__init__.py`, a `base.py` with the class the brokers subclass, and one `<broker>.py` each.
Everything else the subsystem needs - an orchestrator or registry, SQL and its runner, schema
definitions, helpers - goes in a `utilities/` subpackage inside that same package.

`instruments/mapping/`, `instruments/historical/`, `instruments/ticks/` and the REST API's
`broker_funds/`, `broker_holdings/`, `broker_orders/`, `broker_positions/` and `broker_quotes/` all read this
way, which is what makes "which brokers are implemented here" a question answered by listing the
directory. In `historical/` and `ticks/` the module Flattrade and Shoonya share, as deployments of one
platform, sits beside them as `noren.py`.

The top level of the repository is deliberately small - `stock_brokers/`, `unified_broker_interface/`,
`utilities/`, `test_runs/`, `docs/`, `bin/`, `services/` - and a helper script belongs in the existing
`utilities` package rather than in a new folder of its own.

## `utilities` at every level

There is a `utilities` package at the project root, one in `unified_broker_interface`, and a `utilities/`
subpackage inside each per-broker package, and they are different things. The root one holds configuration,
the shared clients and the helpers every `bin/` script uses; the nested ones hold what their own package
needs beside its broker modules. All keep the descriptive name rather than being shortened to `utils`, so
imports read plainly and none is mistaken for a scratch drawer.

## Self-contained scripts, not shared socket classes

A broker's quote feed, order update feed and pollers are scripts in `bin/<broker>/`, and each carries its own
connection, decoding and normalization rather than inheriting them from a shared class. A script logs in
through the broker's API class in `stock_brokers.api`, logs in again when its token is refused, and writes
what it reads to Redis under keys named for the broker. Each script's module docstring is its full reference,
and the [normalized contracts](contracts.md) are what keeps the output of every broker's scripts the same
shape.

## Two connections per broker, not one

Each broker's `order_updates` script holds its own connection, separate from `quotes`, even where the broker
would allow both on one. A quote feed reconnect then can never drop an order event, and the order stream can
run without spending any market data quota. Flattrade permits only one websocket per session, so there
`flattrade@order_updates` is not run and its orders come from the poller alone. See
[Known issues](../contributing/known-issues.md#broker-limits).

## What a subclass has to write

The base classes are built so that a broker module is only the part that is genuinely
broker-specific.

| Subsystem | A subclass implements | Everything else |
| --- | --- | --- |
| REST | `__init__` (the login flow) and `_request` | `get`, `post`, `put`, `patch`, `delete` |
| Instruments | `download()`, plus the dedupe key | Cleaning, de-duplication, the database write, the row count canary |
| Mapping | `BROKER_NAME` and a rules file; `classify`, `to_identity` or `read_raw_rows` only where the rules cannot say it | Classification, identity, the upsert |
| Price history | Six class attributes, `fetch_candles` and `parse_response` | The rate limiter, the queue, the watermarks, the backoff, the upsert |
| Tick normalization | `feed_key` and the class attributes stating lots, close policy and trusted timestamps | Resolution plans, unit conversion, rounding, instants |
| REST API orders | `fetch_orders`, `fetch_trades`, `normalize_order`, `normalize_trade`, `is_authentication_error`; `build_place`, `build_modify` and `build_cancel` where `WRITES_ENABLED` | Asking every broker, resolution, routing, rate limits |
