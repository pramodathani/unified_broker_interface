# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_store.py`

## Why these three keys are a cache and not the record

`unified.synthetic_order_events` is the record. Everything here can be rebuilt from it, including the fourth key, `unified:orders:parents:intents`,, and recovery does exactly that on every start. A Redis that was flushed therefore costs the engine a slower start rather than a lost position, which is the whole reason the event table exists.

They are worth keeping anyway. A parent's current state is read far more often than it is written — by the engine deciding what to do next, and by anyone looking at what the engine is doing — and reading it from Redis costs one round trip against a scan of the day's events.

## Why the expiry is 06:00 IST

The same boundary `unified:order-updates` uses, moved forward by every write. No order lives across it: a parent still open at 06:00 belonged to a session that ended, and the recovery scan reads events from the same moment. Using one boundary for the cache, the record's scan window and the brokers' own merged hashes means there is one answer to "which day is this", rather than three that can disagree at the edges.

## Why `rebuild` deletes before it writes

`save` adds and updates, which is right for one parent changing. `rebuild` replaces the whole cache from what recovery reconstructed, and it deletes the four keys first.

The reason is a parent the event log no longer knows about — rows deleted by hand, or a Redis holding yesterday's keys because the expiry never fired. Writing over the top would leave that parent in the open set, where recovery would find it again at every start and never resolve it. Deleting first means the cache says exactly what the record says and nothing more.

## Why intent ids are kept

`unified:orders:parents:intents` maps each intent id to the parent it started. The engine acknowledges an intent only after pushing its answer, so an engine that stops between sending an order and acknowledging its intent reads that intent again at its next start. Before this key existed, the only thing between that second reading and a second live order was the stale-intent check, which passes any intent read within its grace period. systemd restarts the engine after 15 seconds and the grace is 30, so a quick restart could place the same order twice.

Every order type saves its parent right after `record_received` and before its first leg is sent, so by the time a request can have left the machine, the intent id is in this key. If that save fails, the event log still has the intent id, and recovery's `rebuild` writes the key from the log before the engine reads any intent, so a crash followed by a restart is covered either way. The one gap left is a Redis save that fails inside a running engine followed by an error that sends the loop back to its pending entries, which would take two independent failures in one pass.
