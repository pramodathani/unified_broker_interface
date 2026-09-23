# Notes on `bin/unified/orders/virtual_book`

The script is deliberately thin: a class that installs the signal handlers, builds `VirtualBook` over the shared Redis client and the engine's `ParentStore`, and runs it. The logic lives in `unified_broker_interface/utilities/order_engine/utilities/virtual_book.py` so the offline suite `test_runs/virtual_queue.py` can run it against a stand-in Redis.

It follows the user's rule that the `__main__` guard only builds the application object and calls its method, rather than the `main()` function most other `bin/` scripts use.

It runs under the existing `unified-orders@.service` template as `unified-orders@virtual_book.service`, so it needs no unit file of its own. Like the order engine it is left out of the target's default install list, because it only matters when `virtual_limit` orders are placed.
