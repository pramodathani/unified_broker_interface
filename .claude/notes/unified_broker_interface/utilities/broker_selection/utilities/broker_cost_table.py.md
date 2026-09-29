# Notes on `unified_broker_interface/utilities/broker_selection/utilities/broker_cost_table.py`

## Why the table is in PostgreSQL

The first plan put the table in a CSV file in the repository. The user asked for a PostgreSQL table instead, `unified.broker_order_costs`, so the values live with the rest of the unified schema and can be changed with SQL.

## Why it is read once a day and not per order

The user asked that the table not be read on the order path, so it adds no latency to a placement. It is read at start-up and again at 06:00 IST, the same moment the daily order counts expire, which is before any market opens. A reload builds a whole new dictionary and replaces `rows` in one assignment, which Python performs atomically, so a reader never sees half a table.

## Why building the table reads nothing

`unified_broker_interface/blueprints/orders.py` builds its `OrdersBlueprint` when the module is imported, and the offline suites import that module. A read in the constructor would make every import reach PostgreSQL, and on a machine without the database the connection attempt waits for the operating system's TCP timeout. So the first read is an explicit `start`, which only `api.py` and the order engine call. The suites never call it, and an empty table makes every limit fall back to configuration, which is exactly the behaviour their recordings were made with.

## Why a database error and an empty table raise different exceptions

The order engine exits with code 2 on a configuration error, and its systemd unit does not restart on 2, so a mistake that cannot fix itself does not become a crash loop. An empty table is such a mistake. An unreachable database is not: it usually comes back on its own, so `load` lets `psycopg2.Error` through, the engine exits with 1, and systemd restarts it.

## Why a failed reload keeps yesterday's rows

A reload that fails at 06:00 would otherwise leave the processes without costs for a whole trading day, or stop them. Yesterday's rows are almost always still right, so they stay in use and the error is logged with its traceback.
