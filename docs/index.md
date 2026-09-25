---
hide:
  - navigation
---

# Unified Broker Interface

<div class="hero" markdown>

<p class="lead">The Unified Broker Interface (UBI) logs in to ten Indian stock brokers at once and presents them as <strong>one trading account behind one REST API</strong>. Your program asks for a quote, a position or an order book once, and the answer already covers every broker. When you place an order, you name the instrument, and the API decides which broker sends it.</p>

</div>

<figure class="diagram">
--8<-- "docs/assets/diagrams/overview.svg"
<figcaption>Orange dots are market data, orders and positions moving from the brokers towards your program. The blue dot is an order going the other way, to one broker.</figcaption>
</figure>

## Start here

The site is split into tabs along the top. Most readers want the first card.

<div class="grid cards" markdown>

-   :material-api:{ .lg .middle } **REST API endpoints**

    ---

    All 26 routes of the UBI API, laid out one group per page with request parameters, `curl` examples, JSON responses and status codes.

    [:octicons-arrow-right-24: Go to the API reference](rest-api/index.md)

-   :material-rocket-launch:{ .lg .middle } **Get started**

    ---

    Install the project, start Redis, MongoDB and TimescaleDB, fill in `.env`, and make your first API call.

    [:octicons-arrow-right-24: Installation](get-started/index.md)

-   :material-layers-triple:{ .lg .middle } **Architecture**

    ---

    The three layers, the stores between them, the data shapes every broker is converted into, and why things are built the way they are.

    [:octicons-arrow-right-24: How it fits together](architecture/index.md)

-   :material-pipe:{ .lg .middle } **Data pipelines**

    ---

    Follow one tick, one order update or one instrument master from the broker's server all the way to the API.

    [:octicons-arrow-right-24: Follow the data](pipelines/index.md)

-   :material-bank:{ .lg .middle } **Brokers**

    ---

    Which of the ten brokers supports what, as a matrix and a chart, with each broker's peculiarities.

    [:octicons-arrow-right-24: Broker coverage](brokers/index.md)

-   :material-cog-play:{ .lg .middle } **Operations**

    ---

    The systemd services, the daily schedule in IST, every script in `bin/`, and the offline test suites.

    [:octicons-arrow-right-24: Run it](operations/index.md)

</div>

## The project in numbers

The table below counts what the repository holds today, so you can judge the size of each part before you read about it.

| What | Count | Where |
|---|---:|---|
| Brokers | 10 | `stock_brokers/api/` |
| REST API routes | 26 | `unified_broker_interface/blueprints/` |
| Endpoint groups (blueprints) | 7 | session, users, brokers, exchanges, instruments, portfolio, orders |
| Synthetic order types in the order engine | 42 | `unified_broker_interface/utilities/order_engine/` |
| Data stores | 3 | Redis, MongoDB, TimescaleDB |
| Offline test suites | 11 | `test_runs/` |

## What one API call replaces

Without UBI, a program that trades through several brokers has to speak each broker's own dialect. The comparison below shows what changes.

| Task | Without UBI | With UBI |
|---|---|---|
| Log in | Ten different flows, some through a headless browser and a TOTP | `POST /api/session/connect` once a day |
| Name an instrument | Ten different token formats and symbol spellings | One `instrument_id`, or exchange, segment and symbol |
| Read positions | Ten requests, ten response shapes | `GET /api/portfolio/positions` |
| Read a live price | Ten websocket protocols | `GET /api/instruments/ltp` |
| Place an order | Choose a broker, then build its own request | `POST /api/orders/place`; the API chooses the broker |
| Close everything in an emergency | Cancel and close at every broker by hand | `POST /api/orders/flatten` |

!!! danger "This software trades real money"
    The order routes send real orders to real broker accounts, and the scripts under `bin/<broker>/` log in to live accounts. Read [Orders](rest-api/orders.md) before calling anything that places, changes or cancels an order.
