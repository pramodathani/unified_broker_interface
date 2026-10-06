# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

The project connects to ten Indian stock brokers (Dhan, Flattrade, Fyers, Groww, INDmoney, Kotak, Shoonya, Stoxkart, Wisdom Capital and Zerodha) and presents them as one account. Broker scripts collect sessions, quotes, orders, positions, instrument masters and candles into Redis and TimescaleDB, unified scripts combine every broker's data into one view, and a Flask REST API serves that view.

The `docs/` directory is a detailed MkDocs site and is the authoritative reference. Read the relevant page before changing a subsystem. The REST API has its own tab, `docs/rest-api/`, with one page per endpoint group.

## Commands

There is no `pyproject.toml`, no build step and no pytest suite. The project root must be on `PYTHONPATH`; `.env` sets it, and running modules with `python -m` from the project root also works. Use `.venv/bin/python` (Python 3.14).

| Task | Command |
| --- | --- |
| Install dependencies | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| Start Redis, MongoDB and TimescaleDB | `docker compose up -d --wait` (the containers in `docker-compose.yml`) |
| Lint | `.venv/bin/ruff check .` (ruff 0.11.2, no config file, so default rules) |
| Offline candle parser tests | `python -m test_runs.candle_parse` |
| Offline session calendar tests | `python -m test_runs.unified_ticks_sessions` |
| Offline order route tests | `python -m test_runs.order_routes` (`--record` rewrites `test_runs/fixtures/order_routes.jsonl` after an intended change) |
| Offline order engine route tests | `python -m test_runs.order_engine_routes` (engine placement mode; its own fixture, because `--record` rewrites a whole file) |
| Offline order list tests | `python -m test_runs.order_change_lists` (the `orders` list form of `modify` and `cancel`; its own fixture) |
| Offline engine change tests | `python -m test_runs.order_engine_changes` (modify, cancel and parent routes on orders the engine placed, through the real engine; its own fixture) |
| Offline place list tests | `python -m test_runs.order_place_lists` (the `orders` list form of `place` through the real engine, and reading an answer back by `intent_id`; its own fixture) |
| Offline order engine tests | `python -m test_runs.order_engine` (the daemon itself, against scripted intents and stubbed brokers) |
| Offline broker selection tests | `python -m test_runs.broker_selection` (the lowest-cost selector's rankings from the cost table, its pacing, and the table's loading, against scripted rows and counts) |
| Offline margin calculator tests | `python -m test_runs.margin_calculators` (every broker's margin calculator request against the bodies the live brokers accepted on 2026-09-30, and their recorded answers; its own fixture) |
| Measure every broker's margin surcharge | `bin/unified/orders/margin_calibration` (calls the brokers' read-only margin calculators with the logins in Redis; `--dry-run` prints without writing `unified.broker_order_costs`; its timer runs it at 09:30 IST on weekdays) |
| Measure what filled orders cost beyond brokerage | `bin/unified/orders/execution_costs` (reads the order engine's event log and `unified.ticks`, never a broker; `--dry-run` prints without writing `unified.order_execution_costs`; its timer runs it at 23:50 IST on weekdays) |
| Work out each broker's latency cost and answer time | `bin/unified/orders/latency_calibration` (reads `unified.order_execution_costs`; `--dry-run` prints without writing the latency columns of `unified.broker_order_costs`; runs after `execution_costs` in the same unit; nothing reads its columns yet) |
| Check the pre-trade cost estimate against measured orders | `bin/unified/orders/estimate_check` (reads only; rebuilds each measured leg's book from `unified.ticks` and compares the estimate with its measured cost; `--days` to change the 20-day window) |
| Offline pre-trade estimate tests | `python -m test_runs.pre_trade_estimate` (the book walk, daily volatility and volume, the impact coefficients, the estimate and the estimate check, against a stand-in database) |
| Offline execution cost tests | `python -m test_runs.execution_costs` (how a fill's cost is split into delay, latency, half spread and impact, which legs count, the write, and the latency calibration's figures, against a stand-in database) |
| Offline funds check tests | `python -m test_runs.funds_check` (the margin estimate against the brokers' own calculators of 2026-09-30, hedge benefit, and which brokers the selector passes over for funds, against a scripted funds document) |
| Offline order engine load test | `python -m test_runs.order_engine_throughput` (broker lanes against ten stub brokers that take 200 ms; about 11 seconds) |
| Offline flatten route tests | `python -m test_runs.order_flatten` (the panic button; pins that cancels are sent before closes) |
| Offline instrument route tests | `python -m test_runs.instrument_routes` (`/details` to `/ticks` against a stubbed mapping cache, quote cache, brokers and tick table; its own fixture) |
| Offline contract size rule tests | `python -m test_runs.contract_sizes` |
| Offline candle cache tests | `python -m test_runs.price_cache` |
| Offline synthetic order book tests | `python -m test_runs.virtual_queue` (the queue estimate and the process that keeps it) |
| Offline websocket feed tests | `python -m test_runs.websocket_feeds` (every broker's quotes and order sockets against scripted connections; name brokers to run only those, and `--record` rewrites only their lines) |
| Run the synthetic limit order book | `bin/unified/orders/virtual_book` (beside the order engine; follows every order the engine holds) |
| Decide a date's currency and commodity contract sizes | `python -m stock_brokers.instruments.mapping.utilities.contract_sizes --date 2026-09-15` (the daily mapping run does this itself) |
| Decide which instrument every live derivative is written on | `python -m stock_brokers.instruments.mapping.utilities.underlyings --date 2026-09-28` (the daily mapping run does this itself; `--dry-run` prints the decisions without writing `unified.underlyings`) |
| Offline example program tests | `python -m test_runs.examples` (runs every program under `examples/` and compares its output with the `.out` beside it; name folders to run only those, `--record` rewrites their `.out` files, `--coverage` lists classes with fewer than two programs and public methods no program calls) |
| Offline connection warming tests | `python -m test_runs.connection_warming` (a local HTTP server that misbehaves; about 40 seconds) |
| Download instrument masters | `python -m test_runs.download_instruments zerodha dhan` (no arguments means every broker) |
| Apply broker schema and instrument DDL | `python -m stock_brokers.instruments.sql.apply_ddl` |
| Apply price history DDL | `python -m stock_brokers.instruments.historical.utilities.sql.apply_ddl` |
| Apply unified mapping DDL | `python -m stock_brokers.instruments.mapping.utilities.sql.apply_ddl` |
| Run the REST API | `bin/rest-api` (gunicorn on 127.0.0.1:8080), or `bin/rest-api --dev` for Flask's development server |
| Run the order engine | `bin/unified/orders/order_engine` (the REST API hands it every order to place; run one) |
| Check every systemd unit and start the ones that are down | `bin/check-services` (`--check-only` to report without starting) |
| Wait until Redis has finished loading its dataset | `bin/wait-for-redis` (`--timeout-seconds` to wait other than five minutes) |
| REST API test page | `bin/rest-api-app` (Streamlit on port 8501; start the API first) |
| Check every broker API is reachable | `bin/check-broker-connections` (logs in to live accounts) |
| Search a broker's instrument master | `bin/search-instruments zerodha INFY` (`--show-columns` lists what that broker is searched on) |
| Load the REST API's detail collections | `bin/import-api-details /path/to/exports` (`--calendars-only` re-copies trading hours and holidays) |
| Show one Zerodha symbol's master row, LTP, OHLC and book | `bin/zerodha-quote INFY` (a live Zerodha account) |
| Docs, live reload | `mkdocs serve` |
| Docs, as CI builds them | `mkdocs build --strict` (`.github/workflows/docs.yml` runs it on every pull request and publishes `main` to https://pramodathani.github.io/unified_broker_interface/) |

Lint is not clean on an untouched tree. `ruff check .` reports 41 findings on `main`, almost all of them in `stock_brokers/api/` and `test_runs/`: star imports and the names they hide (`F403`, `F405`), assigned but unused variables (`F841`), comparisons to `True` and `False` with `==` (`E712`), unused imports (`F401`) and one lambda bound to a name (`E731`). Treat that as the baseline, and judge a change by whether it adds a finding rather than by whether the run is silent.

The offline suites are plain scripts, not pytest files, so there is no way to run a single case other than editing or importing the module. They need no Redis, database, credentials or network, though `order_routes` imports the API and so reads `.env`. `order_routes` compares the order routes' statuses, bodies, outgoing broker requests and Redis round trips with a recording, running the real order engine behind the place route on the same thread, so a refactor of `unified_broker_interface/blueprints/orders.py` or of the engine must leave it unchanged.

`test_runs/broker_login_test.py` logs in to live broker accounts, and anything under `bin/<broker>/` reaches real trading accounts, so do not run them without the user's say-so. Two scripts at the top of `bin/` do the same from outside that directory pattern: `bin/check-broker-connections` authenticates to every broker in turn, and `bin/zerodha-quote` calls three live Kite endpoints. Both only read, but several brokers log in by driving a headless Chrome and consuming a TOTP, so running either one repeatedly means authenticating for real each time.

## Architecture

The system is three independent layers over shared stores. Each layer can run without the others, and each broker's scripts run without any other broker's.

```text
broker APIs and websockets
        │
        ▼
bin/<broker>/*/*        the only code that talks to a broker
        │  writes <broker>:* keys and Redis Streams
        ▼
Redis ──── bin/<broker>/*/store_*_to_db ──► TimescaleDB schema <broker>.*
        │
        ▼
bin/unified/*/*         reads only Redis and the database, never a broker
        │  writes unified:* keys and the unified.* schema
        ▼
unified_broker_interface/   Flask REST API over the unified layer
```

MongoDB holds broker credentials (`settings`) and login tokens (`last_login`), keyed by `broker_name`. Infrastructure locations come from `.env` through `utilities/configurations.py`, which is the one place that opens Redis, MongoDB and PostgreSQL connections.

### Scripts in `bin/`

Every file in `bin/` is an executable, extensionless Python script. Each one starts by calling `utilities.bootstrap.run_under_venv(__file__)`, which re-executes it under `.venv/bin/python`. That is why the scripts work from cron and systemd without an activated environment. The guard compares `sys.prefix`, not interpreter paths, because `.venv/bin/python` is a symlink to the system interpreter.

The `bin/<broker>/` and `bin/unified/` subdirectories hold the long-lived scripts that systemd runs. Each broker's folder is split into five subfolders by subject - `session/` (`connect`, `disconnect`), `user/` (`details`), `orders/` (`api_order_details`, `api_trade_details`, `websocket_order_details`, `store_orders_to_db`), `portfolio/` (`positions`, `holdings`, `funds`, `store_positions_to_db`) and `instruments/` (`daily_feed`, `price_history`, `websocket_quotes`, `store_quotes_to_db`) - and no name repeats within a broker, so a script can be named without its folder. `bin/unified/` is split the same way, with `brokers/` and `exchanges/` added, each holding one `unified_details` script that caches a MongoDB detail collection; `unified_details` is the only name used in more than one folder. Because every script now sits four levels below the project root, its bootstrap line is `sys.path.insert(0, str(Path(__file__).resolve().parents[3]))`, and a script put at the wrong depth cannot import `utilities`. The scripts at the top of `bin/` are standalone tools meant to be typed by hand: `rest-api`, `rest-api-app`, `check-services`, `check-broker-connections`, `search-instruments`, `import-api-details`, `wait-for-redis` and `zerodha-quote`. `wait-for-redis` is also the `ExecStartPre=` of the candle units.

Each script is self-contained apart from the broker classes it runs: pollers carry their own requests and normalization with no shared poller base class, and the two websocket scripts run a socket class from `stock_brokers/websockets/<broker>.py` (see "Per-broker packages") and keep every Redis write, the order and position normalization, arguments, signals and exit codes themselves. `test_runs.websocket_feeds` records what every socket sends, writes and logs, so a change to one is checked offline. A script's module docstring is its full reference, including the field-by-field mapping from the broker's names and its exit codes. Exit code 2 means a bad argument or configuration, and the systemd units deliberately do not restart on it. The seven `<broker>-historical-prices.service` units are the exception: they restart on every exit, because their exit 2 is usually a first login that ran before a data store was ready.

Websocket scripts never write to PostgreSQL. They write a Redis hash of current state plus a capped Redis Stream, and a separate `store_*_to_db` script drains the stream with `COPY` through the consumer group `persist`. The unified scripts read the same streams through the group `unified`.

Orders and positions are written to one hash per broker by two scripts, the REST poller and `websocket_order_details`. A polled row only replaces an entry observed before the poll's request was sent, and that check and write happen together in one Redis Lua script.

### Normalized contracts

Four dictionary shapes keep every broker's output identical: the tick, the order, the position and the unified quote. They are defined in `docs/architecture/contracts.md`. Every key is always present, and a missing field is `None`. Nothing validates them at runtime; each script writes every key out explicitly. Broker spellings of status, product, order type and validity map onto one shared vocabulary, listed in `docs/architecture/contracts.md`, and each `bin/<broker>/` script that normalizes orders carries its own copy of those tables. The broker's untouched payload is always kept beside the normalized one (`data` in Redis, `raw` in the database). Data is stored exactly as the broker sent it, and nothing is corrected or dropped on the way in.

### Per-broker packages

Every package implemented once per broker holds exactly three kinds of file: `__init__.py`, a `base.py` with the class the brokers subclass, and one `<broker>.py` per broker. Everything else that subsystem needs (orchestrators, registries, SQL and its runner, rules files) goes in a `utilities/` subpackage inside that package. Listing the directory therefore answers "which brokers does this support". `noren.py` sits beside Flattrade and Shoonya where they share the Noren platform.

Seven packages read this way: `api/`, `websockets/`, `instruments/mapping/`, `instruments/historical/`, `instruments/ticks/`, `broker_quotes/` and `broker_orders/`. `stock_brokers/instruments/` itself is the exception, and keeps `orchestrator.py` and `sql/` at its own root rather than under `utilities/`.

| Subsystem | Base class | A broker module implements |
| --- | --- | --- |
| `stock_brokers/api/` | `BrokerAPI` | `__init__` (the login flow) and `_request` |
| `stock_brokers/websockets/` | `BrokerWebsocket` | Per socket, `_connect` (open and block until closed) and `_log_in_again`, plus the frame handlers; the socket hands what it decodes to a callback from its script and never writes Redis. A broker's two sockets share one session class. Stoxkart's two streams read a synchronous connection and do not subclass it. |
| `stock_brokers/instruments/` | `BrokerInstruments` | `download()` and the dedupe key |
| `stock_brokers/instruments/mapping/` | `BrokerMappingAdapter` | `BROKER_NAME` and a YAML rules file in `utilities/rules/`; overrides only where rules cannot express it |
| `stock_brokers/instruments/historical/` | `BrokerCandles` | Six class attributes, `fetch_candles` and `parse_response` |
| `stock_brokers/instruments/ticks/` | `TickNormalizer` | `feed_key` and class attributes for lots, close policy and trusted timestamps |
| `unified_broker_interface/utilities/broker_quotes/` | `BrokerQuoteSource` | Fetching a quote and turning it into a tick |
| `unified_broker_interface/utilities/broker_orders/` | `BrokerOrders` | `MARKETS`, the place, modify and cancel requests, `MODIFIABLE_FIELDS`, and reading a success answer; the blueprint does every Redis read |

Adding a broker touches many registries (`INGESTERS`, `ADAPTERS`, `MAPPED_BROKERS`, `DOWNLOADERS`, `NORMALIZERS`, `SOURCES`, `API_CLASSES`, `BROKER_ORDER_CLASSES`, `MARGIN_CALCULATOR_CLASSES`, and the `BROKERS` lists inside each `bin/unified/` combiner). `docs/project/adding-a-broker.md` lists them in order. `MAPPED_BROKERS` in `mapping/utilities/segments.py` is a processing order, not an unordered list.

### Choosing a broker for an order

`POST /api/orders/place` names an instrument, not a broker, so something has to decide which broker receives it. That decision is a class of its own in `unified_broker_interface/utilities/broker_selection/`, subclassing `BrokerSelector` and registered in `BROKER_SELECTOR_CLASSES` in `utilities/registry.py`. Three exist. `lowest_cost.py` is the default: it ranks brokers by the brokerage for the order's category (`fno`, `delivery` or `intraday`) while keeping each inside its per-second, per-minute, per-hour and per-day budgets, and it reads every number from the PostgreSQL table `unified.broker_order_costs`, so its code names no broker, fee or limit. `round_robin.py` keeps its turn counter in the Redis key `unified:orders:round_robin`, so every gunicorn worker shares one rotation. `fixed_priority.py` puts the brokers named in `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY` first and needs no Redis at all. `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` picks between them, and an unknown name stops the API from starting rather than falling back.

The cost table is held in memory by `BrokerCostTable` in `broker_selection/utilities/broker_cost_table.py`, and one instance per process is shared by the selector, `RateBudget` and `DailyOrderCount`. Building it reads nothing, because the orders blueprint is built when its module is imported; `api.py` and the order engine call its `start`, which reads the table once and reloads it every day at 06:00 IST on a background thread. The offline suites never call `start`, so for them the table is empty and every limit falls back to configuration, which is what keeps their recordings unchanged. Where the table gives a limit it replaces `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND` and `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAPS`; those settings now only cover a broker with no row or an empty cell. `docs/architecture/broker-selection.md` explains the ranking and the SQL to change a row.

The lowest-cost selector also passes over any broker that cannot afford the order. `FundsCheck` in `broker_selection/utilities/funds_check.py` estimates the exchange margin from `unified.margin_rates` and live quotes, multiplies it by the broker's measured surcharge (the `margin_multiplier_*` columns of `unified.broker_order_costs`), and compares it with that broker's free cash in `unified:portfolio:funds`, without calling a broker; a basket hands all its legs to the first leg's placement so the whole strategy is checked, optionally with hedge benefit. The check is off until `MarginRateTable.start` has loaded rows, so the offline suites never see it. The surcharges are measured each weekday morning by `bin/unified/orders/margin_calibration`, through one class per broker in `unified_broker_interface/utilities/margin_calculators/` (Stoxkart has no calculator); like the order engine, it is a `bin/unified/` script that calls brokers, but only their read-only margin endpoints. `docs/architecture/broker-selection.md` has the rules and the broker numbers they were checked against.

A selector reads Redis by queueing commands onto the pipeline the order engine already sends to read the instrument (`read_instrument` in `order_engine/utilities/engine_placement.py`), through `queue_redis_commands`, instead of opening a round trip of its own. `docs/rest-api/orders.md` counts the round trips each one costs.

### Order types and holding

The order engine (`unified_broker_interface/utilities/order_engine/`) runs only two classes, `SimpleOrder` and `PlanOrder`, registered in `SYNTHETIC_ORDER_CLASSES`. Every other `synthetic.type` a caller names, all 53 of them in `ROUTED_TYPES` in `utilities/plan_routing.py`, is rewritten on arrival into a `plan` whose one order names that type's preset (`utilities/preset_expander.py`), keeping the name as `routed_from`. A behaviour change to a type is therefore a change to its preset or to the plan engine, never to a class of its own; the fixed classes were retired on 2026-10-03.

Limit orders that would rest at the broker are held in the engine's virtual order book by default and sent only once the other side of the book reaches their price, which saves order messages from each broker's daily cap. `hold_limits` on the request or on one order of a plan decides; a routed type defaults to true when it is in `HOLDING_TYPES`, a hand-written plan to the `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` switch, and the decision is written into the order on arrival so a restart reads it the same way. Exits and profit targets rest at the broker. `docs/rest-api/synthetic-orders.md` under `plan` has the rule and its exceptions.

Plain market orders are not sent to a broker as market orders while `UNIFIED_BROKER_INTERFACE_API_ORDER_MARKET_AS_LIMIT` is on, which is the default. `OrderIntent` turns a plain `MARKET` body into a `marketable_limit`, whose preset is a `peg` on the opposite touch two ticks through it, with `on_empty_book: refuse`, and a 30-second lifetime that cancels. An empty other side, a missing quote or a stale one is answered `409` before anything is sent. After-market orders and bodies that name a `synthetic` type, which includes every closing order `POST /api/orders/flatten` sends, are left as market orders. A marketable limit with `maximum_cost_bps`, which `UNIFIED_BROKER_INTERFACE_API_ORDER_MAXIMUM_COST_BPS` gives every one that sets none, is also refused with `409` when the pre-trade estimate of crossing the spread is above it or the visible book cannot hold it; the setting is unset by default, and `test_runs.order_engine` pins it off. `reaches_size`, which `UNIFIED_BROKER_INTERFACE_API_ORDER_MARKET_REACHES_SIZE` turns on for every marketable limit that sets none, sets the limit as deep into the visible book as the unfilled quantity needs, up to the fifth level; it is off by default and pinned off in the same suite. The offline suites that build the API pin the switch off beside `order_hold_limits`, so their recordings keep their market orders.

### Sessions and logins

A broker API class first tries an authenticated call with the stored token and only logs in (often through headless Chrome, Selenium and a TOTP) when that fails. A successful login writes MongoDB first and the Redis `last_login` hash second. Every request reads the current login through `BrokerAPI._current_login`, so a token obtained by any process is used by all of them without restarts. Constructors must not write the token to Redis, because that races a concurrent login. At Zerodha every login invalidates the previous token, so two independent logins break each other.

`stock_brokers/api/utilities/session.py` `ensure_session` is the cross-process login lock used by `BrokerCandles` and INDmoney's instrument ingester. It keeps separate attempt and success markers and releases locks whose holder process has died.

### Database and DDL

Each broker has its own PostgreSQL schema named after it (`zerodha.ticks`, `zerodha.instruments`, `zerodha.price_history`), and cross-broker data lives in the `unified` schema. There is no shared table with a broker column. Tables are TimescaleDB hypertables.

Schemas live only in numbered `.sql` files under four `sql/ddl/` directories, applied in filename order. There is no migration tool and no version table: every statement must be re-runnable (`IF NOT EXISTS`, `CREATE OR REPLACE`), and adding a column means appending `ALTER TABLE … ADD COLUMN IF NOT EXISTS` to the table's existing file. A file runs inside one transaction, so it must not contain continuous aggregates or `CREATE INDEX CONCURRENTLY`. The tick stream DDL has no runner; each `persist_*` script applies its own broker's file when it starts. `docs/architecture/database.md` has the ordering rules for a fresh database.

### Services

Everything runs as systemd **user** units in `services/<broker>/`, `services/unified/` and `services/databases/`, installed with `systemctl --user link`, so the units expect the repository at `~/Projects/unified_broker_interface`. Each broker has one template per script folder - `<broker>-instruments@.service`, `<broker>-orders@.service`, `<broker>-portfolio@.service` and `<broker>-user@.service` - so `zerodha-orders@api_order_details.service` runs `bin/zerodha/orders/api_order_details`, and the unified layer has the same six for its own folders. Nothing in `session/` runs as a long-lived service. The daily instrument download and mapping job is `unified-mapping.service`, named apart from the `unified-instruments@.service` template that runs the live feeds. Timers run the instrument download and mapping at 07:45 IST every day, broker logins at 07:00 IST every day and unified price history at 08:30 IST from Monday to Saturday. Targets use `WantedBy=default.target`, never `multi-user.target`, which does not exist in the user manager. Each target file's header carries its install commands.

`services/databases/` is the odd group out. It runs `docker compose up -d --wait` once a minute, which starts whatever container is stopped or missing and leaves running ones alone, so the three data stores come back without anyone watching. Its timer repeats on `OnUnitInactiveSec` rather than a clock time, and it is the one unit that sets `Environment=PYTHONPATH=`, because Docker Compose reads the same `.env`, which sets `PYTHONPATH` to the project plus `$PYTHONPATH`, and warns on every run while `$PYTHONPATH` itself is unset.

## Documentation

Docs live with the code and change in the same commit. Narrative pages are hand-written under `docs/` and must be added to `nav` in `mkdocs.yml`. API reference pages are generated at build time from docstrings by `utilities/gen_ref_pages.py`, so a new module appears without edits. Every class also has two or more runnable programs in `examples/<module path>/<ClassName>/`, which `utilities/docs_examples.py` adds to its reference page; a new class needs them, and `docs/project/writing-docs.md` explains how. Cross-reference code with `[`Name`][dotted.path.to.Name]`; `mkdocs build --strict` fails on an unresolvable reference. Use `!!! danger` only for anything that can place a live order or lose data. When a broker is added or its behaviour changes, update the coverage matrix and the broker's tab in `docs/brokers/index.md` and the tables in `docs/operations/scripts.md`. When a route is added or changed, update its page under `docs/rest-api/` and the master table in `docs/rest-api/index.md`; every endpoint page follows the Kite Connect style template described in `docs/project/writing-docs.md`, which also lists the site's visual conventions (method badges, Mermaid, Vega-Lite charts and animated SVG diagrams in `docs/assets/diagrams/`).

## Testing against live feeds

NSE and BSE equity close at 15:30 IST, so an equity feed after hours connects but proves nothing about parsing. MCX trades until 23:30 IST, so use MCX futures for evening tests, through a broker's `quotes` script with `--tokens`. When rolling a pattern out across brokers, take one broker all the way through against the live system before copying it to the others.
