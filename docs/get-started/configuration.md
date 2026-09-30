# Configuration

The system is configured in two places. Environment variables, kept in a `.env` file at the project root, say where the three stores are and tune the REST API. MongoDB documents hold everything secret about the brokers: API keys, passwords, PINs and TOTP seeds. This page lists both.

## How configuration is read

Every Python process reads its settings through one module, `utilities/configurations.py`. The diagram below shows where each kind of setting comes from and which parts of the system read it.

```mermaid
flowchart LR
    ENV[".env file"] -->|load_dotenv| CFG["utilities/configurations.py"]
    ENV -->|same file| DC["docker compose"]
    CFG --> RC["redis_configuration"]
    CFG --> MC["mongodb_configuration"]
    CFG --> PC["postgres_configuration"]
    CFG --> AC["api_configuration"]
    MG[("MongoDB<br/>settings")] --> API["broker API classes<br/>stock_brokers/api/"]
    MG --> UBI["REST API connect<br/>bin/unified/session/connect"]
    RC & MC & PC --> ALL["every script and the REST API"]
    AC --> REST["REST API and order engine"]
```

`configurations.py` calls `load_dotenv()` when it is imported, so a variable already set in the process environment wins over the same variable in `.env`. The module is also the one place that opens connections, through `get_cache()` for Redis, `get_mongo_db()` for MongoDB, and `get_postgres()` and `get_postgres_engine()` for TimescaleDB.

!!! warning "The `.env` file holds live credentials"
    `.env` holds the MongoDB and PostgreSQL passwords that guard every broker's API key, secret and TOTP seed. `.gitignore` excludes it; never commit it.

## Data store variables

Fifteen variables describe the three stores, five for each. The Python code has no defaults for them. The `docker-compose.yml` column shows the default the compose file uses when it starts the container, which only matters to Docker.

| Variable | Type | Read by | Compose default | Notes |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_REDIS_HOST` | text | Python | | Host of the Redis server |
| `UNIFIED_BROKER_INTERFACE_REDIS_PORT` | integer | Python, compose | `1002` | Converted with `int()` on import, so it must be set |
| `UNIFIED_BROKER_INTERFACE_REDIS_DB` | integer | Python | | Redis database number; converted with `int()` on import, so it must be set |
| `UNIFIED_BROKER_INTERFACE_REDIS_USERNAME` | text | Python | | Redis ACL user name; the compose file sets only a password (`--requirepass`) |
| `UNIFIED_BROKER_INTERFACE_REDIS_PASSWORD` | text | Python, compose | | Becomes `--requirepass` in the container |
| `UNIFIED_BROKER_INTERFACE_MONGODB_HOST` | text | Python | | Host of the MongoDB server |
| `UNIFIED_BROKER_INTERFACE_MONGODB_PORT` | integer | Python, compose | `1003` | Converted with `int()` on import, so it must be set |
| `UNIFIED_BROKER_INTERFACE_MONGODB_DB` | text | Python | | The database holding `settings`, `last_login` and the detail collections |
| `UNIFIED_BROKER_INTERFACE_MONGODB_USERNAME` | text | Python, compose | `unified_broker_interface` | Becomes the root user when the container is first initialized |
| `UNIFIED_BROKER_INTERFACE_MONGODB_PASSWORD` | text | Python, compose | | Becomes the root password when the container is first initialized |
| `UNIFIED_BROKER_INTERFACE_POSTGRES_HOST` | text | Python | | Host of the TimescaleDB server |
| `UNIFIED_BROKER_INTERFACE_POSTGRES_PORT` | integer | Python, compose | `1004` | Converted with `int()` on import, so it must be set |
| `UNIFIED_BROKER_INTERFACE_POSTGRES_DB` | text | Python, compose | `unified_broker_interface` | The database holding every schema |
| `UNIFIED_BROKER_INTERFACE_POSTGRES_USERNAME` | text | Python, compose | `unified_broker_interface` | Becomes the database owner when the container is first initialized |
| `UNIFIED_BROKER_INTERFACE_POSTGRES_PASSWORD` | text | Python, compose | | Becomes the owner's password when the container is first initialized |

The MongoDB and PostgreSQL connection strings are built from these values, as `mongodb://user:password@host:port/` and `postgresql://user:password@host:port/database`.

## REST API variables

Twenty-seven variables tune the REST API, the order engine and the order-book pollers. Unlike the store variables, every one of them has a default, so a script that never serves the API does not need them. When `configurations.py` is imported, twenty-six of them are read into `api_configuration`, and `UNIFIED_BROKER_INTERFACE_BOOK_POLL_SECONDS` is read into `book_configuration`.

A list variable is written as comma-separated names, such as `zerodha,dhan`. Spaces are removed and the names are lower-cased before use.

### Serving and sessions

The first three variables decide where the API listens and how long its access token lives.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_HOST` | `127.0.0.1` | text | The address gunicorn, or Flask with `--dev`, binds to | `bin/rest-api`, `unified_broker_interface/api.py`, the test page |
| `UNIFIED_BROKER_INTERFACE_API_PORT` | `8080` | integer | The port the API listens on | `bin/rest-api`, `unified_broker_interface/api.py`, the test page |
| `UNIFIED_BROKER_INTERFACE_API_TOKEN_TTL_SECONDS` | `86400` | integer | How long an access token issued by a connect stays valid | `POST /api/session/connect`, `bin/unified/session/connect` |

### Choosing a broker for an order

These variables decide which broker receives an order placed through `POST /api/orders/place`, and how.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` | `lowest_cost` | `lowest_cost`, `round_robin` or `fixed_priority` | Which broker selection class ranks the brokers; `lowest_cost` is described in [Choosing a broker by cost](../architecture/broker-selection.md). An unknown name stops the API and the engine from starting, rather than falling back. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY` | empty | list | The preference order for `fixed_priority`. Brokers it does not name follow the named ones, in turn order. | `unified_broker_interface/utilities/broker_selection/fixed_priority.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` | empty | list | Brokers that never receive an order. When every broker is excluded, placing answers `503` with `every broker is excluded from order placement`. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |
| `UNIFIED_BROKER_INTERFACE_BOOK_POLL_SECONDS` | unset | decimal | Slows every per-broker order-book and trade-book poller to at least this many seconds between polls. Unset, each keeps its own interval (half a second for most, a second for Stoxkart, five for the Fyers order book and fifteen for the Fyers trade book); it never makes a poller faster than its own interval. Raise it once the brokers' order websockets carry the live state, since each poll downloads the whole day's book | `bin/<broker>/orders/api_order_details`, `api_trade_details` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` | `all` | list | Brokers whose order connections are kept warm by a background thread that rotates through every connection in the pool; `all` means every broker and an empty value turns warming off. An unknown name is logged and ignored. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` | `true` | boolean | Holds every plain `LIMIT` order in the order engine's virtual order book and sends it only when the other side of the book reaches its price, as a [`virtual_limit`](../rest-api/synthetic-orders.md) order. An order that names any `synthetic` type, an `IOC` order, an after-market order and an order without a `price` are sent as they ask. `true`, `1` or `yes` turns it on; anything else turns it off | `unified_broker_interface/utilities/order_engine/utilities/order_intent.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACE_LIST_MAXIMUM` | `500` | integer | The most orders one `POST /api/orders/place` list may hold | the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACE_LIST_WAIT_SECONDS` | `25` | decimal | The longest a list placement waits for the engine's answers; each order adds a tenth of a second to the single form's wait up to this | the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_WORKERS_PER_BROKER` | `10` | text | How many worker threads each broker's lane in the order engine starts with: a number, optionally followed by per-broker overrides, such as `10,zerodha=6` | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DATABASE_CONNECTIONS` | `8` | integer | The most PostgreSQL connections the order engine's workers share for writing `unified.synthetic_order_events` | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_MAXIMUM_WORKERS_PER_BROKER` | `30` | integer | The most worker threads one broker's lane in the order engine may grow to; the engine keeps one more connection than this to each broker | `bin/unified/orders/order_engine` |

### The order engine

These variables tune the order engine, which places every order the REST API accepts.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_TIMEOUT_SECONDS` | `5` | decimal | How long an API worker waits for the engine's answer before it answers that the outcome is unknown | `unified_broker_interface/utilities/order_engine/utilities/intent_handoff.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_RESULT_TTL_SECONDS` | `300` | integer | How long the engine keeps an answer in Redis for a worker that never came back for it | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_RECONCILE_SECONDS` | `5` | decimal | How often the engine compares its open legs with the brokers' polled order books, to learn fills and cancels no order socket delivered; `0` turns off the periodic passes, but the one at start always runs | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` | `30` | decimal | An order the engine reads more than this long after the worker's deadline is answered `409` and recorded, not placed | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_SECOND` | `0` | decimal | Order messages allowed in any one-second span across every broker; zero turns this limit off | `bin/unified/orders/order_engine`, the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND` | `10,zerodha=5,indmoney=5` | text | Order messages (placements, modifications and cancellations) allowed in any one-second span to one broker, shared by the engine and the REST API through Redis: a default, optionally followed by `broker=number` overrides. Zerodha and INDmoney default to 5, because in the live test of 2026-09-27 both refused orders sent at 10 a second. A broker's `orders_per_sec` in `unified.broker_order_costs` replaces this setting, so it now applies only to a broker with no row or an empty cell. An override that names no broker stops the API and the engine from starting | `bin/unified/orders/order_engine`, the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WINDOW_SECONDS` | `1` | decimal | The span the two rate limits are counted over. `1` counts per second exactly; a little more, such as `1.05`, keeps a margin for requests that reach a broker a few milliseconds unevenly, at the cost of a slightly lower rate | `bin/unified/orders/order_engine`, the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WAIT_SECONDS` | `1` | decimal | How long a message waits for room in the rate budget before it is refused | `bin/unified/orders/order_engine`, the REST API |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_LOSS_LIMIT` | `0` | decimal | New orders are refused once the day's realized plus unrealized loss, read from `unified:portfolio:funds`, reaches this. Zero or less turns the check off, and the engine logs a warning at start when it is off. | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_REPRICE_MINIMUM_SECONDS` | `1` | decimal | The shortest time between two price changes of one resting order. Zero turns the check off. | `bin/unified/orders/order_engine` |

### Daily caps and the panic button

The variables below set the daily order caps and how long the panic button waits.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAPS` | empty | `broker=number,…` | Each capped broker's limit on order messages a day, such as `zerodha=5000,dhan=7000,fyers=10000`. Placements, modifications and cancellations all count. A broker's `orders_per_day` in `unified.broker_order_costs` replaces this setting, so it now applies only to a broker the table leaves uncapped. Empty means no broker is capped here. An entry that is not `broker=whole number` stops the API and the engine from starting. | `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAP_EXIT_RESERVE` | `0.05` | decimal share | Once a broker is within this share of its cap, new entries are refused and only messages that close a position are sent, up to the cap itself | `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FLATTEN_WAIT_SECONDS` | `5` | decimal | How long `POST /api/orders/flatten` waits for its cancelled orders to leave the brokers' order books before it closes positions | `unified_broker_interface/blueprints/orders.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_CHECK` | `true` | `true` or `false` | Whether the lowest-cost selector passes over a broker that cannot afford an order. It also needs `unified.margin_rates` to hold rows; see [Choosing a broker by cost](../architecture/broker-selection.md#checking-that-a-broker-can-afford-the-order) | `unified_broker_interface/utilities/broker_selection/utilities/funds_check.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_MARGIN_CUSHION` | `0.05` | decimal share | Added on top of every margin estimate, so a small move in price before the fill does not turn into a rejection | `unified_broker_interface/utilities/broker_selection/utilities/funds_check.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_MARGIN_DEFAULT_MULTIPLIER` | `1.15` | decimal | The surcharge assumed for a broker whose `margin_multiplier_*` column in `unified.broker_order_costs` is empty, such as Stoxkart, which has no margin calculator to measure it with | `unified_broker_interface/utilities/broker_selection/utilities/funds_check.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_MAXIMUM_AGE_SECONDS` | `5` | decimal | How old a broker's funds in `unified:portfolio:funds` may be before the broker is passed over rather than trusted | `unified_broker_interface/utilities/broker_selection/utilities/funds_check.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_SETTLE_SECONDS` | `2` | decimal | How long after an order is sent a broker's funds reading is trusted to include it; until then the order's margin is subtracted from the broker's free cash | `unified_broker_interface/utilities/broker_selection/utilities/funds_reservations.py` |

!!! danger "These settings govern real orders"
    The order variables decide which live account receives an order and when orders stop. Change them with the API stopped, and test the result with `"dry_run": true` before sending a real order. See [Orders](../rest-api/orders.md).

## Other variables

The remaining variables are read by one module or one script each.

| Variable | Default | Effect | Read by |
|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_LOGIN_MIN_INTERVAL` | `300` | The shortest time, in seconds, between two login attempts for one broker through `ensure_session`, however many processes ask. See [Sessions and logins](../architecture/sessions.md#one-login-at-a-time-across-processes). | `stock_brokers/api/utilities/session.py` |
| `UNIFIED_BROKER_INTERFACE_API_KEY` | none | The REST API's key, used instead of the `--api-key` argument or a prompt | `bin/unified/session/connect`, `bin/unified/session/disconnect` |
| `UNIFIED_BROKER_INTERFACE_API_SECRET` | none | The REST API's secret, used instead of a prompt. There is deliberately no `--api-secret` argument, because a secret on the command line shows in the process list and in shell history. | `bin/unified/session/connect`, `bin/unified/session/disconnect` |
| `PYTHONPATH` | none | Must include the project root when you run project modules with plain `python`. The scripts in `bin/` put the project root on `sys.path` themselves, and `python -m` from the project root also works without it. | Python |
| `UBI_VENV_REEXEC` | set internally | Set by `utilities/bootstrap.py` across its re-execution under `.venv/bin/python`, so a switch that fails to take cannot loop. You never set it. | `utilities/bootstrap.py` |

!!! note "Why the databases unit clears `PYTHONPATH`"
    `.env` sets `PYTHONPATH` to the project plus `$PYTHONPATH`. Docker Compose reads the same `.env` and warns on every run when `$PYTHONPATH` itself is unset, so `services/databases/databases.service` sets `Environment=PYTHONPATH=` to silence it.

## MongoDB documents

MongoDB holds the configuration that differs too much from broker to broker to fit into environment variables. The collections below must exist before the system can run. Every document in `settings` and `last_login` is found by its `broker_name`.

| Collection | Documents | Who writes it | Who reads it |
|---|---|---|---|
| `settings` | One per broker, plus `unified_broker_interface` | You, by hand | Each broker's API class; the REST API's connect; `bin/unified/session/*` |
| `last_login` | One per broker, plus `unified_broker_interface` | Each broker's login; the REST API's connect and disconnect | Each broker's API class; the REST API |
| `exchange_details` | One per exchange, keyed `exchange` | `bin/import-api-details` | `bin/unified/exchanges/unified_details` |
| `broker_details` | One per broker, keyed `broker_name` | `bin/import-api-details` | `bin/unified/brokers/unified_details` |
| `user_details` | The account holder's profiles, no key | `bin/import-api-details` | `bin/unified/user/unified_details` |

### The `settings` documents

Each broker's API class in `stock_brokers/api/<broker>.py` reads a fixed set of fields from its `settings` document. The table below shows which fields each class reads. Only the field names are listed here; the values are your own credentials.

| Field | Dhan | Flattrade | Fyers | Groww | INDmoney | Kotak | Shoonya | Stoxkart | Wisdom Capital | Zerodha |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `api_key` | | :material-check: | | | | :material-check: | | :material-check: | :material-check: | :material-check: |
| `api_secret` | | :material-check: | | | | | :material-check: | :material-check: | :material-check: | :material-check: |
| `api_password` | | | | | | | | :material-check: | | |
| `app_id` | | | :material-check: | | | | | | | |
| `client_id` | :material-check: | | | | :material-check: | | | | | |
| `fy_id` | | | :material-check: | | | | | | | |
| `mobile_number` | | | | | | :material-check: | | | | |
| `mpin` | | | | | :material-check: | :material-check: | | | | |
| `password` | | :material-check: | | | | | :material-check: | | legacy | :material-check: |
| `pin` | :material-check: | | :material-check: | | | | | | legacy | |
| `price_api_key` | | | | | | | | | :material-check: | |
| `price_api_secret` | | | | | | | | | :material-check: | |
| `publisher_api_key` | | | | | | | | :material-check: | | |
| `publisher_api_secret` | | | | | | | | :material-check: | | |
| `redirect_uri` | | | optional | | | | | | | |
| `secret_key` | | | :material-check: | | | | | | | |
| `totp_secret` | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | | :material-check: |
| `totp_token` | | | | :material-check: | | | | | | |
| `ucc_code` | | | | | | :material-check: | :material-check: | :material-check: | :material-check: | |
| `username` | | :material-check: | | | | | | | | :material-check: |
| `vendor_code` | | | | | | | :material-check: | | | |

A few cells need a word of explanation:

- **Wisdom Capital** logs in with two key pairs. `api_key` and `api_secret` open the trading session, and `price_api_key` and `price_api_secret` open the separate market data session. `password` and `pin` are read only by an older browser login that the class keeps switched off (`_USE_LEGACY_LOGIN = False`).
- **Fyers** falls back to `https://localhost` when `redirect_uri` is missing.
- **Stoxkart** needs `publisher_api_key` and `publisher_api_secret` in addition to the app's own `api_key` and `api_secret`, and its constructor raises an error naming them when they are missing.
- **`totp_secret`** is the seed of the account's authenticator, from which the code computes the current six-digit code with `pyotp`.

The REST API's own document, with `broker_name` `unified_broker_interface`, holds `api_key` and `api_secret`. Those are the values a client sends as the `api-key` and `api-secret` headers to `POST /api/session/connect`, and the values `bin/unified/session/connect` checks.

!!! note "The settings are also copied into Redis"
    Every time a broker's API class is constructed, `BrokerAPI.__init__` writes that broker's `settings` document into the Redis hash `settings`, under the broker's name. The REST API's order routes read the hash from there, so the credentials are also present in Redis.

### The `last_login` documents

You never write `last_login` yourself; a login writes it. Every document carries `broker_name`, `access_token` and `last_login`, the local time of the login as text. Some brokers add fields, as the table below shows.

| Document | Extra fields | Time format of `last_login` |
|---|---|---|
| `dhan`, `flattrade`, `fyers`, `indmoney` | none | `%Y-%m-%d %H:%M:%S` |
| `groww`, `shoonya`, `stoxkart`, `zerodha` | none | `%Y-%m-%d %H:%M:%S.%f` |
| `kotak` | `sid`, `base_url` (the API host Kotak assigned to the session) | `%Y-%m-%d %H:%M:%S.%f` |
| `wisdom_capital` | `market_data_access_token`, `market_data_user_id`, `market_data_last_login` | `%Y-%m-%d %H:%M:%S` |
| `unified_broker_interface` | `expires_at` | `%Y-%m-%d %H:%M:%S.%f` |

Each document is mirrored as JSON into the Redis hash `last_login`, under the same `broker_name`. [Sessions and logins](../architecture/sessions.md) explains why the order of those two writes matters.
