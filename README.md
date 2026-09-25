# Unified Broker Interface

One normalized interface over ten Indian retail brokers. Each broker speaks its own REST dialect, its own websocket protocol and its own vocabulary for the same order, and this project maps all of them onto a single shape, so that the code above it never has to branch on which broker a message came from.

A tick from Zerodha and a tick from Shoonya are the same dictionary with the same keys. A field the broker does not supply is `None` rather than missing. The same holds for orders and positions, right down to a shared vocabulary for order status, product and validity.

> [!CAUTION]
> This project places real orders with real money. The scripts under `bin/<broker>/`, `bin/check-broker-connections`, `bin/zerodha-quote` and `test_runs/broker_login_test.py` all reach live trading accounts, and `POST /api/orders/place` on the REST API places an order at a broker.

## How it fits together

Three layers sit over three shared data stores. Each layer runs without the others, and each broker's scripts run without any other broker's.

```text
broker REST APIs and websockets
        │
        ▼
bin/<broker>/*/*        the only code that ever talks to a broker
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

The three stores each do one job. MongoDB holds broker credentials and login tokens, because what each broker needs differs too much in shape for columns. Redis holds current state and the streams that buffer every feed, which keeps the database off the websocket scripts entirely. TimescaleDB holds the time series, where hypertables give compression and retention.

## Broker coverage

Ten brokers are implemented. A dash means no module or script exists for that capability, not that the broker cannot do it.

| Broker | REST | Quotes | Order updates | Positions streamed | Instruments | Mapping | Price history |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Zerodha | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Dhan | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Flattrade | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Shoonya | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Fyers | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Groww | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Kotak | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| INDmoney | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Wisdom Capital | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Stoxkart | ✓ | ✓ | ✓ | — | ✓ | ✓ | — |

The gaps have reasons rather than being work left undone. Only four brokers send position updates on their order update socket, so only those four have a `store_positions_to_db`; every broker's positions still arrive through its `positions` poller. Groww answers 403 on the historical endpoint, which is an entitlement rather than a bug, while Kotak and Stoxkart publish no candle endpoint at all. `docs/brokers/index.md` carries the full matrix and the reason behind every dash.

## Requirements

| Requirement | Version used here | Why |
| --- | --- | --- |
| Python | 3.14 | The virtual environment in `.venv` is built against it |
| Redis | 6 or later | Queues and current state |
| MongoDB | 8.0.4 | Broker credentials and login tokens |
| PostgreSQL with TimescaleDB | 18 | Ticks, order updates, positions, instruments and price history |
| Google Chrome and chromedriver | current stable | Several brokers log in through Selenium |
| TA-Lib C library | 0.6 or later | The `TA-Lib` package in `requirements.txt` wraps it |

Docker Compose runs the three stores, so Redis, MongoDB and TimescaleDB need not be installed on the host.

## Getting started

Nothing runs until the environment is filled in, because `utilities/configurations.py` reads it at import time and casts the port numbers with `int()`. A missing variable therefore fails on the very first import rather than later at connection time, so if an import raises before your own code runs, look at `.env` first.

1. **Create the virtual environment and install the dependencies.** The MkDocs packages are in the same file, so this installs the documentation toolchain too.

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install -r requirements.txt
   ```

2. **Write a `.env` file at the project root.** It needs a `PYTHONPATH` entry pointing at the project, because there is no `pyproject.toml` installing the packages, and one host, port, database, username and password for each of the three stores. `docs/get-started/configuration.md` lists every variable with its default. This file holds live trading credentials and is excluded by `.gitignore`; never commit it.

3. **Bring the data stores up.** Docker Compose reads the same `.env`, so the ports and passwords come from the variables you just set.

   ```bash
   docker compose up -d --wait
   ```

   Each store keeps its data in a bind-mounted folder under `/mnt/ubi/docker-volumes/`, so a recreated container keeps its data. Note that MongoDB and PostgreSQL apply their credentials only when that folder is first initialised, so changing a password in `.env` afterwards does not change it inside the database.

4. **Create the PostgreSQL objects.** The broker schemas, the instrument tables and the price history tables have runners; the per-broker tick tables do not, because each `persist_*` script applies its own broker's file when it starts.

   ```bash
   .venv/bin/python -m stock_brokers.instruments.sql.apply_ddl
   .venv/bin/python -m stock_brokers.instruments.historical.utilities.sql.apply_ddl
   ```

5. **Put each broker's credentials into MongoDB.** One document per broker in the `settings` collection, keyed by `broker_name`. What it holds differs by broker: an API key and secret for the OAuth brokers, a username, password and TOTP seed for the ones driven through Selenium. The matching `last_login` collection is written by the login flow itself, not by you.

Once that is done, `bin/check-broker-connections` authenticates to every broker and reports which ones answered. Be aware that it logs in for real.

## What is where

```text
bin/
├── <broker>/              the only code that talks to a broker: logins, pollers, feeds, persisters
├── unified/               combines every broker from Redis and the database alone
└── rest-api, check-services, search-instruments, …    standalone tools, run by hand

stock_brokers/
├── api/                   one authenticated session class per broker
└── instruments/           instrument masters, and mapping/, historical/ and ticks/ beneath it

unified_broker_interface/  the Flask REST API: blueprints/ and utilities/
utilities/                 the environment and the clients built from it, and the venv bootstrap
services/                  systemd user units, one folder per broker plus unified/ and databases/
test_runs/                 offline suites, the Streamlit test page, and a live login check
docs/                      the MkDocs site
```

A package that implements something once per broker holds exactly three kinds of file: `__init__.py`, a `base.py` with the class the brokers subclass, and one `<broker>.py` each. Everything else that subsystem needs goes into a `utilities/` subpackage beside them. That is what makes "which brokers are supported here" a question answered by listing a directory.

## Running it

The REST API serves the unified layer over HTTP. A client logs in with an API key and secret, receives an access token, and sends that token with every other request.

```bash
bin/rest-api               # gunicorn on 127.0.0.1:8080
bin/rest-api --dev         # Flask's development server, for local debugging
bin/rest-api-app           # a Streamlit page to poke at the API, on port 8501
```

In production everything runs as systemd **user** units, linked from `services/` rather than copied, so the units expect the repository at `~/Projects/unified_broker_interface`. Each folder's target file carries its own install commands in its header. Timers log every broker in at 07:00 IST, download and map the instrument masters at 07:45, and fetch the unified price history at 08:30 from Monday to Saturday. A separate `databases` unit runs `docker compose up -d --wait` every minute, so a stopped container comes back on its own.

```bash
bin/check-services               # check every unit and start the ones that are down
bin/check-services --check-only  # report without starting anything
```

## Tests and lint

There is no pytest suite. The five offline suites are plain scripts that need no Redis, database, credentials or network, and they are run as modules.

```bash
.venv/bin/python -m test_runs.candle_parse            # broker candle parsers
.venv/bin/python -m test_runs.unified_ticks_sessions  # trading session calendars
.venv/bin/python -m test_runs.order_routes            # the REST API's order routes, against a recording
.venv/bin/python -m test_runs.order_engine_routes     # the place route in engine mode, against its own recording
.venv/bin/python -m test_runs.order_engine            # the order engine daemon, against scripted intents
.venv/bin/python -m test_runs.contract_sizes          # currency and commodity contract size rules
.venv/bin/python -m test_runs.connection_warming      # a local HTTP server that misbehaves; about 40 seconds
.venv/bin/ruff check .                                # ruff 0.11.2, no config file, so default rules
```

`order_routes` compares every route's status, body, outgoing broker request and Redis round trip against a stored recording, so a refactor of the orders blueprint has to leave it unchanged; `--record` rewrites the recording after an intended change. Lint is not clean on an untouched tree, and reports 41 findings concentrated in `stock_brokers/api/` and `test_runs/`, so judge a change by whether it adds a finding rather than by whether the run is silent.

## Documentation

The `docs/` directory is a full MkDocs site and is the authoritative reference for every subsystem. It is published at https://pramodathani.github.io/unified_broker_interface/, and the REST API endpoints are under its REST API tab. Narrative pages are hand-written, and the API reference is generated from docstrings at build time, so a new module appears without any edit.

```bash
mkdocs serve           # http://127.0.0.1:8000, with live reload
mkdocs build --strict  # what CI runs: broken links and references fail the build
```

Two pages are worth knowing about before you change anything. `docs/rest-api/index.md` lists every REST API endpoint and links to one page per endpoint group. `docs/project/adding-a-broker.md` walks through the registries a new broker has to be added to, in order.
