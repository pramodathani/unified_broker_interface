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

Nineteen variables tune the REST API and the order engine. Unlike the store variables, every one of them has a default, so a script that never serves the API does not need them. They are read into `api_configuration` when `configurations.py` is imported.

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
| `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` | `direct` | `direct` or `engine` | `direct` sends the order from the API worker. `engine` hands it to `bin/unified/orders/order_engine` through a Redis Stream. Any other value stops the worker from starting. | `unified_broker_interface/blueprints/orders.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` | `round_robin` | `round_robin` or `fixed_priority` | Which broker selection class ranks the brokers. An unknown name stops the API and the engine from starting, rather than falling back. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY` | empty | list | The preference order for `fixed_priority`. Brokers it does not name follow the named ones, in turn order. | `unified_broker_interface/utilities/broker_selection/fixed_priority.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` | empty | list | Brokers that never receive an order. When every broker is excluded, placing answers `503` with `every broker is excluded from order placement`. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` | empty | list | Brokers whose order host is pinged on a background thread to keep a connection open. An unknown name is logged and ignored. | `unified_broker_interface/utilities/broker_orders/utilities/placement.py` |

### The order engine

These variables matter only when `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is `engine`.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_TIMEOUT_SECONDS` | `5` | decimal | How long an API worker waits for the engine's answer before it answers that the outcome is unknown | `unified_broker_interface/utilities/order_engine/utilities/intent_handoff.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_RESULT_TTL_SECONDS` | `300` | integer | How long the engine keeps an answer in Redis for a worker that never came back for it | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` | `30` | decimal | An order the engine reads more than this long after the worker's deadline is answered `409` and recorded, not placed | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_SECOND` | `8` | decimal | The engine's overall budget of orders a second, as a token bucket | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND` | `5` | decimal | The same budget for any one broker | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WAIT_SECONDS` | `1` | decimal | How long a burst waits for a token before the order is refused | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_LOSS_LIMIT` | `0` | decimal | New orders are refused once the day's realized plus unrealized loss, read from `unified:portfolio:funds`, reaches this. Zero or less turns the check off, and the engine logs a warning at start when it is off. | `bin/unified/orders/order_engine` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_REPRICE_MINIMUM_SECONDS` | `1` | decimal | The shortest time between two price changes of one resting order. Zero turns the check off. | `bin/unified/orders/order_engine` |

### Daily caps and the panic button

The last three variables apply to both placement modes.

| Variable | Default | Type | Effect | Read by |
|---|---|---|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAPS` | empty | `broker=number,…` | Each capped broker's limit on order messages a day, such as `zerodha=5000,dhan=7000,fyers=10000`. Placements, modifications and cancellations all count. Empty means no broker is capped. An entry that is not `broker=whole number` stops the API and the engine from starting. | `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAP_EXIT_RESERVE` | `0.05` | decimal share | Once a broker is within this share of its cap, new entries are refused and only messages that close a position are sent, up to the cap itself | `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FLATTEN_WAIT_SECONDS` | `5` | decimal | How long `POST /api/orders/flatten` waits for its cancelled orders to leave the brokers' order books before it closes positions | `unified_broker_interface/blueprints/orders.py` |

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
