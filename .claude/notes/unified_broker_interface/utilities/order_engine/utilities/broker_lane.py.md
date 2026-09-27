# Notes on `unified_broker_interface/utilities/order_engine/utilities/broker_lane.py`

## Why a lane per broker

Every broker call blocks its worker for the whole time the broker takes. A lane per broker means a broker that is slow, or whose rate budget is full, holds up only its own workers; the other brokers' orders keep flowing. It also lets the number of workers be set per broker, because the number a broker needs is its rate limit times how long it takes to answer.

## Why a lane grows but never shrinks during the day

Starting a thread was measured on this machine on 2026-09-27 at a median of 54 microseconds and 129 at the 99th percentile, against a broker call of tens to hundreds of milliseconds, so there is no point keeping idle spares ready. A lane starts a worker the moment every existing worker has work.

A worker usually owns parents that are still live, such as a bracket waiting for its entry to fill. Stopping it would mean handing those parents to another thread part way through, which is exactly the sharing the lanes exist to prevent. So workers stay until the engine restarts.

## Why the new worker is started inside the lock

The worker is appended and started while `workers_lock` is held, so two intents arriving together cannot both decide the lane is full and each start a worker past the maximum.
