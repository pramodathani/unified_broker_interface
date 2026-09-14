# Configuration

Configuration arrives from two places. Infrastructure - where Redis, MongoDB and TimescaleDB are -
comes from the environment. Broker credentials come from MongoDB, because they change per broker
and are rewritten by the login flow itself.

## The environment

`utilities/configurations.py` calls `load_dotenv()` on import, so a `.env` file at the project
root is read automatically. Every store variable is required; the port variables are cast with
`int()` at import time and a missing one raises immediately. The REST API's variables are the
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
```

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
