# Notes on `unified_broker_interface/utilities/order_engine/utilities/order_to_trade_ratio.py`

## Why the counters are behind a lock

The broker-lane design runs many worker threads in one engine, and all of them count sends and fills here through `RiskGates`. Updating a dictionary entry is a read and a write, and two threads can interleave between them and lose a count. A `threading.Lock` around each change keeps the counts exact. `counts` takes a copy of the broker names under the lock, so a broker added by another thread while the shutdown line is being written cannot change the dictionary during the loop.
