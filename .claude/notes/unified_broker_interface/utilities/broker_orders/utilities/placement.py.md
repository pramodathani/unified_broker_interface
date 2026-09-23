# Notes on `unified_broker_interface/utilities/broker_orders/utilities/placement.py`

## Why placement moved out of the blueprint

Placing an order is two halves that happen to run in the same method. The first half reads Redis and belongs to the route: the access token, the mapping date, the logins and settings, the instrument's catalogue entry, the brokers' turn. The second half reads nothing: it ranks the brokers, picks the first that can take the order, builds that broker's request, sends it and reads the answer.

Only the second half is of any use to `bin/unified/orders/order_engine`, and until this change the only way to reach it was to build a Flask blueprint, which brings two Redis pipelines and a route table with it. `OrderPlacement` is that second half with nothing else attached.

## The rule this class was written to keep

`.claude/notes/unified_broker_interface/blueprints/orders.py.md` records the rule that replaced the old one-method rule: every Redis read the order routes make is in the blueprint, and the only network call is `BrokerOrders.send`. That rule is what lets anyone count what an order costs by reading one file, and it is load-bearing, because the endpoint this replaced took about half a second and most of that was the API's own work.

`OrderPlacement` keeps the rule by reading no store at all. The caller reads Redis and hands in the decoded texts: `login_texts`, `settings_texts`, `selector_replies` and an `Instrument` that has already been decoded. That is also why the class can sit under `broker_orders/`, whose package docstring already promises that nothing in it reads a store.

## Why `rotation` is still called by the blueprint

`rotation()` is a method here, but `place_order` in the blueprint calls it and passes the result in, rather than letting `place()` call it. That looks like an oversight and is not.

The refusal it raises, when configuration has excluded every broker, must happen before the second Redis pipeline is sent. `test_runs/fixtures/order_routes.jsonl` records the `every_broker_excluded` scenario as HTTP 503 after exactly one Redis round trip. Had the call moved inside `place()`, the refusal would have been raised after the second pipeline and the recording would have had to change from one round trip to two — which is exactly the kind of quiet extra round trip the rule above exists to prevent.

## The compromise: this class knows the REST answer's shape

`dry_run_answer` and `send` return the REST API's own body, key for key, including `timing_ms` and `broker_response`. A class under `broker_orders/` knowing what an HTTP answer looks like is uncomfortable, and it was chosen with the alternative in view.

The alternative is to return the prepared placement and the broker's answer and let each caller build its own body. That means the order engine carries a second copy of the same fifteen lines. The entire promise of the engine is that a caller cannot tell which process placed the order, so those two copies would have to be kept identical by hand, for ever, with a recording that only checks one of them. One awkward dependency is cheaper than two bodies that must never disagree.

## Why `place` is four methods rather than one

`prepare`, `dry_run_answer` and `send` exist separately because the engine needs to interleave its own work between them, not because `place` was too long. `place` itself is three lines and is what the REST API calls.

The file is larger than the code that left the blueprint — 382 lines against 322 removed. All of the difference is the module docstring, the class docstring, and the `Args`, `Returns` and `Raises` sections on four method signatures where there was previously one long method tail. No logic was added, which the unchanged recording is the evidence for.
