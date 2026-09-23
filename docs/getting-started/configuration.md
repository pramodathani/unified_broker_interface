# Configuration

Configuration arrives from two places. Infrastructure - where Redis, MongoDB and TimescaleDB are -
comes from the environment. Broker credentials come from MongoDB, because they change per broker
and are rewritten by the login flow itself.

## The environment

`utilities/configurations.py` calls `load_dotenv()` on import, so a `.env` file at the project
root is read automatically. Every store variable is required; the port variables and
`UNIFIED_BROKER_INTERFACE_REDIS_DB` are cast with `int()` at import time and a missing one raises immediately. The REST API's variables and the login interval are the
exception: they are optional, with the defaults shown.

```bash title=".env"
PYTHONPATH=/home/you/Projects/unified_broker_interface

UNIFIED_BROKER_INTERFACE_REDIS_HOST=127.0.0.1
UNIFIED_BROKER_INTERFACE_REDIS_PORT=6379
UNIFIED_BROKER_INTERFACE_REDIS_DB=0
UNIFIED_BROKER_INTERFACE_REDIS_USERNAME=default
UNIFIED_BROKER_INTERFACE_REDIS_PASSWORD=

UNIFIED_BROKER_INTERFACE_MONGODB_HOST=127.0.0.1
UNIFIED_BROKER_INTERFACE_MONGODB_PORT=27017
UNIFIED_BROKER_INTERFACE_MONGODB_DB=unified_broker_interface
UNIFIED_BROKER_INTERFACE_MONGODB_USERNAME=
UNIFIED_BROKER_INTERFACE_MONGODB_PASSWORD=

UNIFIED_BROKER_INTERFACE_POSTGRES_HOST=127.0.0.1
UNIFIED_BROKER_INTERFACE_POSTGRES_PORT=5432
UNIFIED_BROKER_INTERFACE_POSTGRES_DB=unified_broker_interface
UNIFIED_BROKER_INTERFACE_POSTGRES_USERNAME=
UNIFIED_BROKER_INTERFACE_POSTGRES_PASSWORD=

# Optional: the REST API, see Guides > REST API
UNIFIED_BROKER_INTERFACE_API_HOST=127.0.0.1
UNIFIED_BROKER_INTERFACE_API_PORT=8080
UNIFIED_BROKER_INTERFACE_API_TOKEN_TTL_SECONDS=86400
UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS=
UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR=round_robin
UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY=
UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS=

# Optional: the order engine
UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT=direct
UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_TIMEOUT_SECONDS=5
UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_RESULT_TTL_SECONDS=300
UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS=30
UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_SECOND=8
UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND=5
UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WAIT_SECONDS=1
UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_LOSS_LIMIT=0

# Optional: the shortest time, in seconds, between ensure_session login attempts for one broker
UNIFIED_BROKER_INTERFACE_LOGIN_MIN_INTERVAL=300
```

`UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` chooses where an order is sent from. At `direct`,
which is the default and today's behaviour, the API worker that accepted the order also sends it to
the broker. At `engine`, the worker writes the order to a Redis stream and waits for
`bin/unified/orders/order_engine` to place it and answer. Any other value stops the worker from
starting, the same way an unknown broker selector does. The three `..._ORDER_ENGINE_...` variables
are read only in `engine` mode: how long a worker waits for the engine's answer before giving up
with HTTP 504, how long that answer is kept for a worker that never collected it, and how far past
its deadline an order may be before the engine records it rather than placing it into a market that
has moved.

The order engine's risk gates are the last four. `..._ORDER_RATE_PER_SECOND` and
`..._ORDER_RATE_PER_BROKER_PER_SECOND` are a token bucket across every broker and for any one of them, defaulting well
under the ten orders a second that SEBI's retail algorithmic trading framework treats as algorithmic trading needing
registration. An order that finds the bucket empty waits up to `..._ORDER_RATE_WAIT_SECONDS` for a token and is
refused with HTTP 503 only if none arrives, because a burst within one tenth of a second is ordinary and a short delay
beats a refusal.

`..._ORDER_DAILY_LOSS_LIMIT` is the most the day may lose, realized plus unrealized across every broker, before the
engine refuses new orders with HTTP 403. **It is off at zero, which is the default**, and the engine warns at startup
when it is, because a limit guessed on your behalf would be worse than none: too low it stops a normal day, too high it
is theatre. Unrealized loss counts, because a position held at a loss has lost the money whether or not it has been
closed.

These are limits on placements. `PUT /api/orders/modify` and `DELETE /api/orders/cancel` still go straight from an API
worker to a broker and are not counted against the rate budget.

!!! danger "`.env` holds live trading credentials"

    The MongoDB and PostgreSQL passwords in this file guard the collection that holds every
    broker API key, secret and TOTP seed. Never commit it. The `.gitignore` at the project root
    excludes it.

## The clients built from it

Everything opens its connections through one module, so there is a single place that knows where
each store is.

| Helper | Returns | Used by |
| --- | --- | --- |
| [`get_cache()`][utilities.configurations.get_cache] | Redis client, `decode_responses=True` | The API classes and the `bin/` scripts |
| [`get_mongo_db()`][utilities.configurations.get_mongo_db] | MongoDB database handle | The API classes and the `bin/` scripts |
| [`get_postgres()`][utilities.configurations.get_postgres] | psycopg2 connection | The persisters, which `COPY` a fixed column list |
| [`get_postgres_engine()`][utilities.configurations.get_postgres_engine] | SQLAlchemy engine | The instrument loader and the DDL runner |
| [`get_logger()`][utilities.configurations.get_logger] | Named logger, e.g. `zerodha.quotes` | Everything |

The two Postgres helpers exist for different callers rather than by accident: the persisters want
a raw connection because they `COPY` a known column list, while the instrument loader writes
whatever columns the broker published that day off a pandas `DataFrame`, and `DataFrame.to_sql`
needs an engine.

## Broker credentials in MongoDB

Two collections, both keyed by `broker_name`.

=== "settings"

    Written by you, once per broker. What each broker needs differs - an api key and secret for
    the OAuth brokers, a username, password and TOTP seed for the ones driven through Selenium.

    ```json
    {
      "broker_name": "zerodha",
      "api_key": "…",
      "api_secret": "…",
      "username": "…",
      "password": "…",
      "totp_secret": "…"
    }
    ```

=== "last_login"

    Written by the login flow, not by you. Each broker's API class upserts the access token it
    obtained and the timestamp, and mirrors it into Redis under the `last_login` hash.

    ```json
    {
      "broker_name": "zerodha",
      "access_token": "…",
      "last_login": "2026-09-12 08:55:03.412887"
    }
    ```

[`BrokerAPI.__init__`][stock_brokers.api.base.BrokerAPI] reads both collections and copies
`settings` into the Redis hash of the same name. It does not copy `last_login`: that Redis hash is
written only by a login, which writes MongoDB first and Redis second.

Every REST request reads the login in force at that moment through
`BrokerAPI._current_login`, so a token another process has
just obtained is used by the very next request, with no need to rebuild the API object. It takes
the newer of Redis's login and the object's own - the object's wins only when it is genuinely
newer, such as a login whose Redis write failed - and when Redis holds nothing it reads MongoDB and
fills the empty field without overwriting a login that lands in between.

!!! note "Why constructors do not write the token"

    A constructor that read `last_login` from MongoDB and then wrote it to Redis would race a login: a
    process that read MongoDB just before another logged in, and wrote Redis just after, would put the old
    token back for everyone reading Redis.

## How a login actually happens

The brokers split into two camps, and the difference shows up in what `settings` must contain.

**Token brokers** exchange an api key and secret for an access token over REST. Nothing
interactive is involved.

**Selenium brokers** have no such flow, so the API class drives a headless Chrome through the
broker's own login page. Zerodha is the clearest example: it first tries an authenticated call,
and only when that fails does it open `kite.trade/connect/login`, fill in the username and
password, generate the current TOTP from `totp_secret` with `pyotp`, wait for the redirect
carrying `request_token`, and exchange that plus a SHA-256 checksum for an access token.

That "try a call first, log in only if it fails" pattern is why constructing an API object is
cheap when a token from earlier in the day is still valid, and slow the first time each morning.
