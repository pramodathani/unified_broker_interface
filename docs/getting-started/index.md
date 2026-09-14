# Getting started

Three steps, in order. Nothing in the project runs until the environment is filled in, because
`utilities.configurations` reads it at import time.

1. [Installation](installation.md) - the virtual environment and the Python dependencies.
2. [Configuration](configuration.md) - the `.env` file and the per-broker credentials in MongoDB.
3. [Data stores](data-stores.md) - Redis, MongoDB and TimescaleDB, and creating the tables.

!!! tip "Order matters"

    `utilities/configurations.py` calls `int(os.getenv(...))` on the port numbers at module
    import. A missing or empty `UNIFIED_BROKER_INTERFACE_REDIS_PORT` therefore fails with a
    `TypeError` on the very first import, not later at connection time. If an import of anything
    under `stock_brokers` raises before your own code runs, the `.env` file is the first place to
    look.
