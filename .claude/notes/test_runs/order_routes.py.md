# Notes on `test_runs/order_routes.py`

## Why the suite exists

The suite was written on 2026-09-15, before `POST /api/orders/place` and `DELETE /api/orders/cancel` were split out of one long method each into per-broker order classes, a pluggable broker selector and an in-process instrument cache. Placing an order had by then been confirmed live at every broker, so the refactor had to send byte-for-byte the same requests. The recording in `test_runs/fixtures/order_routes.jsonl` was made from the code as it stood before any of that work, and every later step was checked against it.

## What is compared, and why those things

Each scenario keeps four things: the HTTP status, the response body, every request that would have reached a broker, and the number of Redis round trips.

- The outgoing request is captured by replacing `requests.Session.request`, not read from a dry run's answer, because a dry run leaves out the session headers, the timeout and the certificate check, and those differ by broker. `Session.post` calls `Session.request`, so the capture works whichever of the two the code calls.
- `timing_ms` is reduced to its sorted key names, because the values change on every run while the keys are part of the response's shape.
- The round-trip count is what guards the endpoint's latency rule: a refactor that quietly adds a Redis read changes it.

Groww's `order_reference_id` contains random hex from `uuid.uuid4`, so the suite replaces `uuid.uuid4` with a constant while it runs.

## How the blueprint is given the stand-ins

`BaseBlueprint.__init__` calls `get_cache` and `get_mongo_db` through names imported into `unified_broker_interface.blueprints.base`, so the suite replaces those two names on that module and builds a fresh `OrdersBlueprint` for each scenario. Replacing them on `utilities.configurations` would have no effect, because `base` has already bound its own references. The module-level `orders_bp` is still built once at import with real clients, which open no connection until a command is sent.

A fresh blueprint per scenario means nothing a worker remembers leaks from one scenario into the next. The scenarios with `steps` send several requests through one blueprint on purpose, to show what a worker remembers between requests.

## The round-robin counter

The stand-in's `INCR` returns the stored value plus one, so a scenario's `counter` is stored as `counter - 1`. `counter_for` adds ten to a broker's position so the stored value is never negative.

## Why the recording is JSON Lines

One scenario per line keeps a re-recording's diff readable: an intended change shows up as the changed lines only, and each line names its scenario. The file is about 380 kilobytes.

## The stored orders and token hashes the modify scenarios need

A modification restates the stored order, so on 2026-09-15 the ten open orders in `ORDER_IDENTIFIERS` were given full normalized fields, and further orders were added under ids no cancel scenario uses. A cancel's answer echoes only the stored status, so the added fields left every recorded cancel unchanged.

`add_instrument` also fills one `tokens:<broker>` hash per broker, as the warm does, and a BSE instrument `RELBSE` shares RELIANCE's token 2885, so the scenarios can show a token naming instruments on two exchanges. Its symbol differs from RELIANCE so that no placement's catalogue range read reaches it, and placements never read the token hashes, which is why none of the 457 earlier scenarios changed.

