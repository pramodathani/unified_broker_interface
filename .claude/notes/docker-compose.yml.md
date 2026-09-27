# Notes on `docker-compose.yml`

## Why TimescaleDB's `shm_size` is 4g

PostgreSQL puts the shared state of a parallel query (tuple queues, and the shared hash table of a parallel hash join) in dynamic shared memory, which on Linux is a file in `/dev/shm`. Docker gives a container 64 MB there unless `shm_size` says otherwise, and the image's `timescaledb-tune` settings allow 16 workers per query and 32 in total, with `work_mem` of about 31 MB and `hash_mem_multiplier` of 2.

The limit was 1 GB until 27 September 2026. On 26 September the unified price history job (`unified-prices.service`) failed in its `verify` step with `could not resize shared memory segment "/PostgreSQL.3596208362" to 268435456 bytes: No space left on device`. Running `verify` alone afterwards, while the seven broker candle services were running as usual, took `/dev/shm` to a peak of 527 MB from that one query, so a second heavy parallel query at the same moment is enough to pass 1 GB.

4 GB leaves room for several such queries at once. `/dev/shm` is a tmpfs, so the limit reserves nothing; the machine has 123 GB of RAM. Lowering parallelism for the job instead was rejected because it would slow a check that already takes over twenty minutes, and any other large query could still hit the same wall.

## Applying a change here restarts the database

`services/databases/databases.service` runs `docker compose up -d --wait` from the main checkout once a minute, and Compose recreates a container whose settings changed. So pulling a change to this file into the main checkout restarts PostgreSQL within a minute, for a few seconds, and every service holding a database connection sees it drop.
