# Notes on `test_runs/order_change_lists.py`

## Why it is a separate suite with its own fixture

`--record` rewrites a whole fixture. `order_routes.jsonl` is the evidence that restructuring `modify` and `cancel` around `PreparedModification` and `PreparedCancel` left the single form unchanged, so the list scenarios live in their own file, as `order_engine_routes.py.md` explains for the engine scenarios.

## What is reused

Everything that makes a scenario comparable with the single form comes from `test_runs/order_routes.py`: the Redis stand-in, the starting order books, logins and settings, `open_request`, `send` and `run_scenario`. `OrderChangeListSuite` subclasses `OrderRoutesSuite` and replaces only the scenario list, the fixture path and the network stand-in. `record`, `read_recording` and `compare` are copied because the originals read a module-level path.

## Why the network stand-in was widened

The order suite's network gives every request in a scenario one shared answer. A list sends to several brokers from several threads, so `ListBrokerNetwork` picks the answer per request by a URL fragment, which lets one scenario have Dhan refuse while Zerodha accepts, and it appends captured requests under a lock.

## Why captured requests are sorted

A list's requests leave on up to four threads, so the order they reach the network differs from run to run. They are recorded sorted by their JSON, which keeps the recording stable while still pinning every URL, header, body, timeout and certificate check. The `timing_ms` keys inside each entry are reduced to their names, as the order suite does for a single answer.

## Numbers worth watching in the recording

- `cancel_list_sixty_unknown_orders_one_round_trip` costs one Redis round trip for 60 orders.
- `modify_list_every_broker` costs three round trips for ten orders. It cost eleven before `warm_order_instruments` was added.
- The Groww entry in the every-broker scenarios answers 422, because Groww does not read the shared "success" reply as a success. The single-form recording has the same result for `cancel_groww_answer_success`.
