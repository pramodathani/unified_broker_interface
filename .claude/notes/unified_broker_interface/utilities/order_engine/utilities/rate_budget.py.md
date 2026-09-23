# Notes on `unified_broker_interface/utilities/order_engine/utilities/rate_budget.py`

## Why the budget is in this process and not in Redis

The build plan put the token bucket in a Redis key, on the reasonable assumption that several things might be sending orders. By the time this was written the engine already had `unified:orders:engine:lock`, which allows exactly one engine to run and exits the second one rather than letting it wait.

Given that, an in-process bucket is exactly correct and a great deal simpler: no Lua script, no round trip on the order path, no key to reason about when it expires. The lock is what makes it correct, so the two belong together in anybody's head — weaken the lock and this becomes wrong.

## Why an order waits rather than being refused

A burst of orders arriving inside the same tenth of a second is ordinary: a strategy reacting to one signal may place four legs at once. Refusing them because the bucket happened to be empty would push the retry logic onto every caller, and a caller retrying immediately makes the burst worse.

So `take` waits up to a configured second for a token and refuses only a burst that outlasts the whole wait. The wait is interruptible by the engine's stop event, so SIGTERM does not have to sit through it.

## Why both tokens are taken together or neither

The global bucket and the broker's are taken in one step, and a global token is given back if the broker's bucket is empty. Without that, an order waiting on a busy broker would take a global token on every attempt, draining the budget that other brokers were about to use, and the global limit would bind far earlier than it should.

## What this does not cover, said plainly

The engine sends placements. `PUT /api/orders/modify` and `DELETE /api/orders/cancel` still go straight from an API worker to a broker, and they count against an exchange's order rate exactly as a placement does. Until they are routed through the engine, this is a budget on placements rather than on everything the account sends.

That matters most for the order types Stage 8 adds. A chaser walking towards the touch, or a peg following the mid, consumes its budget in modifications rather than placements, so those types cannot be trusted to respect this budget until modifications go through it too.
