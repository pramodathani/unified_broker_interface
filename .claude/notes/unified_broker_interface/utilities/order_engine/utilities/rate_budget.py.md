# Notes on `unified_broker_interface/utilities/order_engine/utilities/rate_budget.py`

## Why a sliding window and not a token bucket

The budget used to be two token buckets in the engine's memory, one global and one per broker, each holding as many tokens as it earned in a second. A bucket like that is a smoothing device, not a hard limit. Full, it sends its whole capacity at once and then one more every tenth of a second, which is nineteen messages inside one second for a bucket of ten. The user set the limit at 10 order messages a second per broker as a compliance line, so the budget has to guarantee that no one-second span ever holds an eleventh message.

A sliding window guarantees exactly that. Each broker's sorted set holds the send time of every message in the last second; a message is allowed only when fewer than ten remain after the older ones are dropped. Checked against the live Redis on 2026-09-27 by sending 25 messages as fast as possible with a limit of 10: the first ten went at once, the eleventh at 1.001 seconds, all 25 were sent in 2.00 seconds, and no one-second span held more than 10.

## Why it moved into Redis

The plan for broker lanes runs many worker threads in the engine and keeps the REST API sending modifications and cancellations from its gunicorn workers. An exchange counts every one of those messages against the same account. A budget in one process's memory cannot see the others, so the only place a shared limit can live is somewhere both kinds of process reach, and Redis is already that place.

The check and the write are one Lua script, which Redis runs without interleaving any other command, so two processes can never both see nine messages and both send a tenth. The time comes from `redis.call('TIME')`, the Redis server's clock, so the engine and a gunicorn worker whose clocks disagree still count against one timeline. The set expires two seconds after its last write, so an idle broker costs nothing.

It costs one Redis round trip per message, about a tenth of a millisecond, against a broker call of tens to hundreds. The engine's recordings show that as one extra round trip for each order sent through its gates.

## Why the limit across every broker is off by default

The compliance limit is per broker: each broker is a separate account, and SEBI's threshold applies to each. Total throughput is meant to grow as brokers are added. The global limit is kept, counted in the same step under `unified:orders:rate:all`, for anyone who wants to cap the total, but its default is zero, which turns it off.

## Why a member is random rather than the time

Two messages can arrive in the same microsecond, and a sorted set keeps one member per name. Naming each message with `secrets.token_hex(8)` keeps both. `uuid.uuid4` is not used because the offline suites replace it with a counter to make ids repeatable, and a budget drawing on that counter would shift every id they record.

## Why a Redis failure refuses rather than sends

When the script cannot run, `RiskGates.take_rate_token` turns the Redis error into a 503 refusal, which the order type records against the leg as rejected, and the REST API answers 503 for a modification or cancellation. Sending without the budget would be sending past a compliance limit without knowing it, which is worse than a refused order that can be sent again a moment later. The error is turned into a refusal rather than left to rise because the leg has already been recorded as `sending` by then; an exception would leave it there, and recovery would later find no order at the broker and park the whole parent as failed.

## Why some brokers have their own limit

In the live burst of 2026-09-27 the sliding window held every broker to 10 messages in any second, and still Zerodha refused 10 of its 20 orders (`Maximum allowed order requests per second exceeded`) and INDmoney 4 of 20 (`Rate limit exceeded`). Either their limits are lower than 10 as this engine counts, or they count every API call, including the order-book polls the pollers make twice a second. The limit is therefore set per broker, in the same `default,broker=number` form as the worker counts, and defaults to 5 for these two. The 5 is a cautious guess, not a measured limit; a weekday burst after this change is what should settle it.
