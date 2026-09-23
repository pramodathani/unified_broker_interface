# Notes on `unified_broker_interface/utilities/order_engine/engine_runner.py`

## Why an intent is acknowledged after the answer is pushed

The order is: place, push the answer, acknowledge. An engine that dies between placing and acknowledging therefore redelivers that intent at its next start.

That is deliberate, and it is safe only because of the deadline rule. By the time an engine has restarted, the intent is almost always past its deadline plus the grace, so it is answered 409 and recorded rather than placed a second time. The narrow window where an engine dies and restarts within seconds, and the order was already sent, is exactly the recovery gap that the parent order event log is being built to close; until then it is a window, not a solution, and it is recorded here so nobody reads the current order as safer than it is.

Acknowledging before placing would be worse in the other direction: an engine that died before sending would silently lose the order, and the caller would be told the outcome was unknown when in fact nothing happened.

## Why the loop's shape was copied rather than invented

The pending-first read, the doubling backoff to a minute, and the `stop.wait` instead of `time.sleep` all come from `bin/unified/orders/store_orders_to_db`. They are not incidental: reading pending entries before new ones at every start and after every failure is what stops a failed batch being overtaken by newer work, and `stop.wait` is what lets SIGTERM interrupt a backoff rather than waiting it out. `docs/contributing/pitfalls.md` records both a signal handler installed too late and a drain loop that counted the wrong thing, so the shape is worth copying exactly.

## Why a failure to place does not stop the engine

`handle` catches everything. A refusal becomes the caller's answer, and any other exception becomes a 504 saying the outcome is unknown. Neither stops the loop.

The reason is that one bad order must not stop every order behind it. An instrument whose catalogue entry is malformed, or a broker class that raises on a field it has never seen, would otherwise take order entry down for the whole account until someone noticed. The engine is the only path to a broker in this mode, so its availability is the system's availability.

## Why the counters are on the object rather than logged per order

`placed`, `refused` and `expired` are read at shutdown and by the offline recording. Logging a line per order would be the obvious alternative, and was avoided because the log is already the place a person looks for something that went wrong; a healthy engine placing a few hundred orders a day should be quiet, so that the lines that do appear are all worth reading.
