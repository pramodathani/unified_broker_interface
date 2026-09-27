# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_worker.py`

## Why one thread per worker with an inbox

The engine's rule is that one parent is only ever touched by one thread. The simplest thing that guarantees it is a thread that does its own work one piece at a time, in arrival order, with every piece about a parent sent to the thread that owns it. A `queue.Queue` is the standard library's thread-safe way to hand work to a thread, and the Google guide prefers it to locks for passing data between threads.

A piece of work is a bound method and a tuple of arguments rather than a class per kind of work. The engine hands over four kinds, each already a method on the engine or a ticker, and wrapping each in a class would add four files that only call one method.

## Why the load counts waiting and running work

A lane grows when every worker already has work. Counting what is queued as well as what is running is what makes "has work" true for a worker that is between two pieces, so a burst of intents spreads over new workers rather than piling behind a worker that happens to be idle for a microsecond.

## Why `stop` drains the inbox

`stop` puts a marker at the back of the inbox, so a worker finishes everything handed to it before stopping. An intent handed over but not placed would be read again at the next start anyway, but a caller waiting on it would be told it was lost when the answer was a few milliseconds away. The engine waits at most 50 seconds for its workers, under systemd's `TimeoutStopSec=60`.
