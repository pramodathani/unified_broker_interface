# store_quotes_to_db

## Why the default batch is 10,000 ticks

The default `--batch-size` was 500 until 2026-10-28. During market hours that day the database disk (`nvme0n1`, which holds `/mnt/ubi/docker-volumes/timescaledb`) was congested, with writes waiting 186 ms and about 412 queued, largely behind a 40-minute verification query on `unified.price_history` running on ten parallel workers. Every commit then waited 1 to 2.6 seconds for the write-ahead log, so a writer committing every 500 ticks stored only about 600 to 800 ticks a second while Zerodha and Kotak each sent about 4,500. Their streams hold the newest 1,000,000 entries, about four minutes at that rate, so roughly 85% of their ticks were trimmed before this script read them. The live quotes and the unified store were not affected; only `<broker>.ticks` has the gaps.

After the close, with the disk quiet, a throwaway copy of `kotak.ticks` took 4 ms to commit 500 rows and about 70 ms to commit 10,000, and every batch size stored more than 120,000 rows a second. The batch size therefore costs nothing when the disk is quiet, while on a congested disk the rate is roughly the batch size divided by the commit wait: about 250 ticks a second for 500 at 2 seconds a commit, and about 5,000 for 10,000. The flush interval still writes a partly filled batch after `--flush-interval` seconds, so a quiet stream is not held back.

Zerodha, Kotak, Stoxkart and Dhan carry the day's large quote allocations, so their writers were changed; the other brokers stream at most a few thousand instruments and kept 500.
