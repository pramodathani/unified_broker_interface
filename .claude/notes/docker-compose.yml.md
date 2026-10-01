# Notes on `docker-compose.yml`

## Why TimescaleDB's `shm_size` is 4g

PostgreSQL puts the shared state of a parallel query (tuple queues, and the shared hash table of a parallel hash join) in dynamic shared memory, which on Linux is a file in `/dev/shm`. Docker gives a container 64 MB there unless `shm_size` says otherwise, and the image's `timescaledb-tune` settings allow 16 workers per query and 32 in total, with `work_mem` of about 31 MB and `hash_mem_multiplier` of 2.

The limit was 1 GB until 27 September 2026. On 26 September the unified price history job (`unified-prices.service`) failed in its `verify` step with `could not resize shared memory segment "/PostgreSQL.3596208362" to 268435456 bytes: No space left on device`. Running `verify` alone afterwards, while the seven broker candle services were running as usual, took `/dev/shm` to a peak of 527 MB from that one query, so a second heavy parallel query at the same moment is enough to pass 1 GB.

4 GB leaves room for several such queries at once. `/dev/shm` is a tmpfs, so the limit reserves nothing; the machine has 123 GB of RAM. Lowering parallelism for the job instead was rejected because it would slow a check that already takes over twenty minutes, and any other large query could still hit the same wall.

## Applying a change here restarts the database

`services/databases/databases.service` runs `docker compose up -d --wait` from the main checkout once a minute, and Compose recreates a container whose settings changed. So pulling a change to this file into the main checkout restarts PostgreSQL within a minute, for a few seconds, and every service holding a database connection sees it drop.

## Why Redis runs with `--save ""`

Until 2026-10-01 Redis ran with `--appendonly yes` and its default snapshot rules (`save 3600 1 300 100 60 10000`). With about 2,000 writes a second, the `60 10000` rule started a new snapshot of the whole dataset, 13.6 GB at peak, shortly after the previous one finished: 1,347 snapshots in 50 hours, each taking up to 548 seconds during market hours. Together with the append-only file's own rewrites, that kept `/mnt/ubi` (nvme2n1) about 87% busy at around 100 MB/s with a 430 ms average write wait.

TimescaleDB shares that disk, and every order engine event is an INSERT followed by a COMMIT that waits for the disk. Commits stalled for up to 8.5 seconds, so every order the engine placed or cancelled answered after the REST API's 5-second wait, as a 504, although the order was placed. The live plan test on 2026-10-01 found it.

The append-only file, with `appendfsync everysec` and the RDB preamble its rewrites use, already restores the whole dataset on a restart, so the snapshots protected nothing it did not. Turning them off with `CONFIG SET save ""` on the running server dropped the disk to about 10 MB/s and 5% busy, with commits at a median of 0.3 ms and a worst case of 4 ms over a minute. `--save ""` keeps that across a restart.

Changing this file makes `docker compose up -d`, which `services/databases/` runs every minute, recreate the Redis container, so Redis restarts and reloads its append-only file. Merge a change here at a quiet time.

The longer-term fix is to give Redis its own disk: nvme1n1 is the same model as nvme2n1 and is not mounted. Mounting it needs root.
