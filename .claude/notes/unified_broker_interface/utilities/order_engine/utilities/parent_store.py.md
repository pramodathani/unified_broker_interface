# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_store.py`

## Why these three keys are a cache and not the record

`unified.synthetic_order_events` is the record. Everything here can be rebuilt from it, and recovery does exactly that on every start. A Redis that was flushed therefore costs the engine a slower start rather than a lost position, which is the whole reason the event table exists.

They are worth keeping anyway. A parent's current state is read far more often than it is written — by the engine deciding what to do next, and by anyone looking at what the engine is doing — and reading it from Redis costs one round trip against a scan of the day's events.

## Why the expiry is 06:00 IST

The same boundary `unified:order-updates` uses, moved forward by every write. No order lives across it: a parent still open at 06:00 belonged to a session that ended, and the recovery scan reads events from the same moment. Using one boundary for the cache, the record's scan window and the brokers' own merged hashes means there is one answer to "which day is this", rather than three that can disagree at the edges.

## Why `rebuild` deletes before it writes

`save` adds and updates, which is right for one parent changing. `rebuild` replaces the whole cache from what recovery reconstructed, and it deletes the three keys first.

The reason is a parent the event log no longer knows about — rows deleted by hand, or a Redis holding yesterday's keys because the expiry never fired. Writing over the top would leave that parent in the open set, where recovery would find it again at every start and never resolve it. Deleting first means the cache says exactly what the record says and nothing more.
