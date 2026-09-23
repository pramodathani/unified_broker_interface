# Notes on `unified_broker_interface/utilities/order_engine/utilities/engine_recovery.py`

## Why the rebuild goes to the database and not to Redis

Redis holds the same parents and is far quicker to read. It is not read for state, because the whole purpose of recovery is to be correct when the cache is gone — a flushed Redis, a rebooted machine, a key that expired at 06:00 while the engine was down. Recovery therefore replays `unified.synthetic_order_events` and then overwrites the Redis keys with what it found, so the cache cannot disagree with the record.

Redis is read for one thing: the brokers' own order books, which are not the engine's state but the market's.

## Why it replays through the live path's own method

`ParentOrder.apply_event` is used both by the engine placing an order and by this replay. Writing a second, recovery-only reconstruction would mean the code that matters most on the worst day of the year is the code least often run. As it is, every order all day exercises the path recovery depends on.

## Why failing to recover is fatal

The daemon exits 1 if `recover()` raises. Starting anyway would mean placing new orders while not knowing what is already at a broker, which is worse than not starting: the engine would arm protective legs for positions it cannot see and leave real ones unwatched. Exit 1 rather than 2, so systemd retries in fifteen seconds, because the usual cause is a database that is still coming up.

## Two bugs the live test found that the offline suite could not

Both were found by planting a crashed parent in the real database and starting the real daemon, and neither could have been caught by the offline recording as it stood.

The first was the DDL path. `SyntheticOrderEventLog` computes it by counting parents of its own file, and moving the module one directory deeper left it pointing one level short. The stand-in event log has no table to apply, so nothing noticed until the daemon's first real start. A check that the file exists where the log looks for it is now part of the recording.

The second was `decimal.Decimal`. A `NUMERIC` column comes back as a `Decimal`, which `json.dumps` refuses, so writing a recovered parent to Redis raised. The stand-in returns plain floats, so again the offline suite could not see it. Values are now converted where rows leave the database, which is the one place that has to know the database's types.

The lesson worth keeping is the shape of both: a stand-in that is easier to satisfy than the real thing hides exactly the faults that only appear in production.

## Why an abandoned orphan applies the parent's state

Replaying `orphan_abandoned` sets the parent to `failed`, not only the leg to `unknown`. Before that was fixed, a parent replayed as `received` with an `unknown` leg: not terminal, so the open set kept it for ever, and not in `sending`, so nothing ever looked at it again. It leaked one parent per crash, silently, and only showed up because the live run was done twice.
