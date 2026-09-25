# Notes on `bin/unified/orders/order_engine`

## Why the script is thin

Almost nothing lives here. The script parses arguments, opens Redis, takes the lock, builds the placement, installs signal handlers and calls `OrderEngine.run`. Everything else is in `unified_broker_interface/utilities/order_engine/`.

That differs from `store_orders_to_db`, whose `StreamPersister` sits in the script, and the reason is that the engine shares `OrderPlacement` with the REST API. Code the API imports cannot live in an extensionless file under `bin/`. The split is therefore not a stylistic choice; it follows from the two processes placing orders through the same class, which is the point of the whole design.

## Why no new systemd unit

`services/unified/unified-orders@.service` has `ExecStart=%h/Projects/unified_broker_interface/bin/unified/orders/%i`, so a new file in that folder is already a runnable instance. The unit brings `Restart=always`, `RestartSec=15`, `RestartPreventExitStatus=2` and `TimeoutStopSec=60` with it, and the exit codes here were chosen to match: 2 for a configuration that cannot work, so systemd stops rather than crash-looping and hiding the message; 1 for losing the lock, which is worth retrying because the other engine may be stopping.

It is deliberately left out of the enable list in `unified.target`'s header, because it must not run unless the REST API is in engine mode. An engine reading an empty stream does no harm, but a stream nobody writes to is a service that looks healthy while doing nothing, which is worse than one that was never started.

## Why the lock is taken before anything else

Two engines on the same consumer group would each be handed different entries, and between them they would place every order once — except during a restart, when pending entries are redelivered and both could take the same one. The cost of being wrong is a duplicate live order, so the lock is taken before the placement is even built, and an engine that cannot take it exits rather than waiting.

It is a plain key with a 30 second expiry refreshed every 10, not a Lua-guarded lock, because the failure it guards against is a second copy started by hand or by systemd, not a contended race between many processes. An engine killed outright leaves the key behind for at most 30 seconds.

## What one order costs

Two Redis round trips and one broker call, plus the stream reads and the acknowledgement shared across a batch.

The first round trip reads the mapping marker and every broker's login and settings. It happens per order rather than being cached, because a broker's token can be replaced at any moment by another process, and an order sent with a token replaced ten minutes ago is an order that fails.

The second reads the instrument's catalogue entry and whatever the broker selector queues. The entry comes from the engine's own `InstrumentCache` when it holds one for the current warm, which it usually does after the first order of the day, so most orders pay for this round trip only because `round_robin` still queues its `INCR`. Configured with `fixed_priority`, which queues nothing, a warm engine makes one round trip per order rather than two.

## Why an intent read too late is not placed

Each intent carries the deadline at which the API worker gave up waiting. An engine that was down for two minutes comes back to a stream holding orders whose callers were told the outcome was unknown, and placing them then would put real orders into a market that has moved, in response to a decision made minutes ago.

So an intent read more than `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` past its deadline is answered 409 and recorded rather than sent. The answer is pushed even though nobody is waiting on that key any more, because it costs nothing and because the key is what a later investigation reads.

## Why a bad entry is acknowledged rather than retried

An entry that is not JSON, or whose intent has no reply key, is logged and acknowledged unplaced. Redelivering it for ever would put it at the front of the pending list at every start, and every order written after it would wait behind an entry that can never succeed. The same reasoning is already recorded in `docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`) for the candle writer: an unexpected failure must cost the one item, not the run.

## What the handoff actually costs, measured

The build plan set this stage a gate: if the queue hop added more than a millisecond or two to `timing_ms.preparation`, the design was to be reconsidered before anything was built on top of it. It was measured on 2026-09-23 against the live Redis this project uses, with dry runs, which build the broker request and answer with it without sending anything.

Two hundred dry runs of the same NSE equity order in each mode, through Flask's test client so that only the HTTP transport is excluded, repeated three times:

| Mode | Reported `preparation` | Wall clock, median | Wall clock, 95th |
| --- | --- | --- | --- |
| `direct` | 0.301 to 0.342 ms | 0.525 to 0.579 ms | 0.85 to 1.06 ms |
| `engine` | 0.728 to 0.822 ms | 0.987 to 1.103 ms | about 1.5 ms |

The handoff therefore adds about **0.46 ms**, against a broker call that takes 100 to 300 ms. The gate is passed with a great deal of room.

A narrower measurement of the Redis work alone — the `XADD`, the engine's `RPUSH` and `EXPIRE`, and the `BLPOP` — gave a median of 0.201 ms and a 95th percentile of 0.588 ms over three hundred rounds. The rest of the 0.46 ms is the engine's own two round trips for credentials and the instrument, which is work the API worker used to do itself rather than anything new.

The same run confirmed the whole path end to end: the route resolved RELIANCE from its identity fields, the engine picked the intent up, chose a broker by the rotation and built that broker's real order request, and the answer came back with its `intent_id`. Six hundred and one orders were placed as dry runs, none refused, and every answer was collected by a waiting worker.
