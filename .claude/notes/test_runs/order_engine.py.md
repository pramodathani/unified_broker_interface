# Notes on `test_runs/order_engine.py`

## How a loop that blocks for ever is recorded

`OrderEngine.run` blocks on Redis for new entries and returns only when it is asked to stop, neither of which suits a recording that has to finish. The suite hands it `OnePassStop`, which reports "keep going" for a fixed number of checks and "stop" afterwards, so the loop makes exactly the passes a scenario needs.

Three passes is what a scenario normally takes: the first reads pending entries and finds none, the second reads the new entries and handles them, and the third finds nothing and the event says stop. The count is recorded with each result as part of the round trips, so a change in the loop's shape shows up as a changed number rather than a hang.

## A bug the recording found, in the stand-in rather than the engine

The first version of the stand-in's `xreadgroup` treated `>` as "entries not currently pending". That is wrong: Redis tracks a last-delivered id per group, and an entry acknowledged is never handed to `>` again. With the wrong version, every entry was delivered a second time on the pass after it was acknowledged, and the recording showed each order placed twice with two broker calls.

It was caught because the counters are recorded. A suite that only checked the reply body would have passed, since the second placement overwrote nothing and the reply looked right. The stand-in now keeps `delivered`, every id ever handed out, separately from `pending`, the ids handed out but not acknowledged, which is what Redis does.

The lesson worth keeping: when a fake stands in for something with a cursor, the cursor has to be faked too, or the fake will be more forgiving than the real thing in exactly the direction that matters.

## Why two orders in one scenario answer with an empty body

`two_orders_take_turns_at_different_brokers` stubs every broker with `{}` and HTTP 200, so both orders come back as outcome `unknown` with "the broker answered without an order id". That looks like a failing scenario and is not.

The thing being recorded is the two URLs in `sent`: the first order goes to Flattrade and the second to Fyers. That is the round-robin rotation advancing inside one process, which is one of the reasons the engine exists — two gunicorn workers each kept their own view of the same counter. A per-broker success body would have made only the first order's answer readable, since each broker reads its order id from its own field.

## Why the lock is checked directly

Losing the lock happens inside the loop, ten seconds of monotonic time after the last refresh, which a recording cannot reach without waiting. The five lock checks therefore call `take`, `refresh` and `release` in sequence against the stand-in, and record what each returned and what the key held afterwards. That covers taking it, refusing a second engine, refreshing it, losing it to another pid, and releasing it.
