# Notes on `bin/unified/orders/execution_costs`

## Why the measurement runs at night instead of on the order path

The first design recorded an "arrival snapshot" of the quote when the engine took an intent. Reading the engine showed that `EnginePlacement.prepare` does not read the live quote at all unless a price reference needs it, and `read_instrument` skips its Redis round trip entirely when the instrument is cached and the selector queues nothing (`fixed_priority`). Adding an `HGET unified:quotes:live` there would have added a round trip in that case, and it would have changed the Redis round trips that `test_runs/order_routes` and the other engine suites record.

Everything needed was already stored. `unified.synthetic_order_events` has the moment of arrival, send, answer and every fill, and `unified.ticks` has the five-level book of every instrument the unified quote feed carries, with an index on `(instrument_id, time DESC)`. A lookup of the latest tick before a moment took about 5 ms on 2026-10-06, and two days of 175 filled legs measured in a third of a second. So the measurement reads both afterwards and the order path is untouched.

The quote the engine sees, `unified:quotes:live`, is fed by the same unified quote stream that `store_quotes_to_db` persists, so the tick history is the same data the engine had, up to the persister's batching.

## Arguments and schedule

`--days` defaults to 2 so that a night the timer missed (the machine was off, the database was down) is measured the next night without anyone noticing. Because a run replaces its days in one transaction, measuring a day twice is harmless.

The timer runs at 23:50 IST, twenty minutes after MCX's evening session closes at 23:30 (23:55 while the United States is on standard time, in which case the last few minutes of that day are caught by the next night's run).

## The summary

The script prints the median and mean total cost and the mean latency per broker. A median latency was printed first, and it was 0.00 at both brokers on the first real run, because the mid-price usually does not move in the 50 to 150 ms a broker takes to answer. The mean keeps a broker that is occasionally slow visible.

## Bootstrap line

Other `bin/` scripts carry a comment above `sys.path.insert` explaining why the guard compares `sys.prefix`. It is left out here under the no-comments rule; the explanation is in `utilities/bootstrap.py` and in CLAUDE.md.
