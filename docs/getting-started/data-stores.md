# Data stores

Three stores, each doing one job.

| Store | Holds | Why this store |
| --- | --- | --- |
| MongoDB | `settings` and `last_login`, one document per broker, and the REST API's detail collections | Credentials differ in shape from broker to broker, so a document store fits better than columns |
| Redis | Sessions, polled snapshots, current state hashes, instrument masters, the unified documents, and the streams the persisters drain | Keeps the database off the websocket scripts entirely |
| TimescaleDB | `ticks`, `order_updates`, `positions`, `instruments` and `price_history` per broker, and the `unified` schema | Hypertables, columnar compression and retention on time series |

## Running the stores with Docker

`docker-compose.yml` in the project root runs all three stores as containers. Each keeps its data in a folder under `/mnt/ubi/docker-volumes/` on a separate NVMe drive, bind-mounted into the container, so the data survives a container being recreated:

```bash
docker compose up -d
```

The `databases` systemd units run the same command every minute, so a container that is stopped or removed comes back on its own. See [Running it as a service](../guides/services.md#installing).

| Service | Image | Host port | Data folder |
| --- | --- | --- | --- |
| `redis` | `redis:trixie` | `UNIFIED_BROKER_INTERFACE_REDIS_PORT` (default 1002) | `/mnt/ubi/docker-volumes/redis` |
| `mongodb` | `mongo:8.0.4` | `UNIFIED_BROKER_INTERFACE_MONGODB_PORT` (default 1003) | `/mnt/ubi/docker-volumes/mongodb` |
| `timescaledb` | `timescale/timescaledb:latest-pg18` | `UNIFIED_BROKER_INTERFACE_POSTGRES_PORT` (default 1004) | `/mnt/ubi/docker-volumes/timescaledb` |

The drive is mounted at `/mnt/ubi` by an `/etc/fstab` entry that names it by UUID, and a drop-in at `/etc/systemd/system/docker.service.d/ubi-mount.conf` sets `RequiresMountsFor=/mnt/ubi`, so Docker does not start at boot until the drive is mounted. Each bind mount also sets `create_host_path: false`. Together they stop a store from starting on an empty folder when the drive is missing: PostgreSQL and MongoDB would initialise a new, empty database there, and the scripts would write into it.

Docker Compose reads the same `.env` as the scripts, so the ports, usernames, passwords and PostgreSQL database name come from the `UNIFIED_BROKER_INTERFACE_*` variables described in [Configuration](configuration.md). Each port is published on every interface of the host, which is why the `*_HOST` variables can name the host's LAN address.

The MongoDB and PostgreSQL credentials are applied only when their data folder is first initialised. Changing `UNIFIED_BROKER_INTERFACE_MONGODB_PASSWORD` or `UNIFIED_BROKER_INTERFACE_POSTGRES_PASSWORD` in `.env` afterwards does not change the password inside the database, and the scripts then fail to log in. Redis is different: it takes `UNIFIED_BROKER_INTERFACE_REDIS_PASSWORD` on every start, so a changed value takes effect the next time the container is recreated.

## Redis as the buffer

No websocket script ever writes to PostgreSQL. Ticks are appended to a Redis stream and a separate
persister script drains it through a consumer group, acknowledging only what it has committed, so if
PostgreSQL is slow or down, ticks accumulate in Redis and the feed itself is unaffected. Each stream is
capped at a maximum length, which bounds the damage if a persister is never started.

Every feed writes two things: a hash holding the current state, keyed by instrument or order id, for
anything that wants to ask "what is it now", and a stream holding every message in arrival order for
the persister - `bin/<broker>/quotes` writes `<broker>:quotes:live` and `<broker>:quotes:stream`, drained
by `bin/<broker>/persist_ticks`. See [Broker scripts](../guides/broker-scripts.md), and
[Redis keys](../architecture/redis-keys.md) for the full list.

## Creating the PostgreSQL objects

Each broker gets its own PostgreSQL schema, named after the broker, holding tables named for
their content - `zerodha.ticks`, `zerodha.order_updates`, `zerodha.positions`,
`zerodha.instruments`, `zerodha.price_history`. There is no shared table with a broker column. Data that
belongs to no single broker is in the `unified` schema. See [Database](../database/index.md).

The broker schemas and instrument tables come from `.sql` files applied in filename order:

```bash
python -m stock_brokers.instruments.sql.apply_ddl
```

The per-broker price history tables have a runner of their own, which `bin/unified/historical_prices` also
applies on every run; neither `bin/<broker>/instruments` nor `bin/<broker>/historical_prices` applies DDL:

```bash
python -m stock_brokers.instruments.historical.utilities.sql.apply_ddl
```

Each broker's tick, order update and position tables are defined in
`stock_brokers/instruments/ticks/utilities/sql/ddl/010_zerodha_streams.sql` to `100_stoxkart_streams.sql`,
and each `bin/<broker>/persist_*` script applies its broker's file when it starts, so they need no step of their
own. To create them without starting a persister, apply a file directly:

```bash
psql -h "$UNIFIED_BROKER_INTERFACE_POSTGRES_HOST" -p "$UNIFIED_BROKER_INTERFACE_POSTGRES_PORT" \
     -U "$UNIFIED_BROKER_INTERFACE_POSTGRES_USERNAME" -d "$UNIFIED_BROKER_INTERFACE_POSTGRES_DB" \
     -f stock_brokers/instruments/ticks/utilities/sql/ddl/010_zerodha_streams.sql
```

The `unified` tables are applied by `bin/unified/map_instruments`, `bin/unified/historical_prices` and the
unified persisters when they run. See [DDL and migrations](../database/ddl.md).

## Verifying the connections

```python
from utilities.configurations import get_cache, get_mongo_db, get_postgres

get_cache().ping()
get_mongo_db().list_collection_names()
with get_postgres() as connection:
    with connection.cursor() as cursor:
        cursor.execute("select extversion from pg_extension where extname = 'timescaledb'")
        print(cursor.fetchone())
```

A `None` from that last query means the TimescaleDB extension is not enabled in this database,
and the hypertable calls in the table creation scripts will fail.
