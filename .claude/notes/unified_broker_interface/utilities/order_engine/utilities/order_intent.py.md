# Notes on `unified_broker_interface/utilities/order_engine/order_intent.py`

## Why the caller's body is carried verbatim

The obvious design is for the API worker to write the validated `PlaceOrderRequest` onto the stream, since it has already built one. That was rejected for two reasons.

The first is drift. Serialising a `PlaceOrderRequest` means writing a serialiser and a matching reader, and every field added to the request afterwards has to be added to both. The day someone forgets, an order reaches a broker missing a field that the validation had accepted, and nothing in either process notices.

The second is that the serialiser would buy nothing. `PlaceOrderRequest.__init__` reads no store, makes no network call and depends on nothing but the body it is given, so the engine rebuilding it from the same bytes cannot reach a different answer than the worker did. The validation the worker performs is not thrown away by re-running it; its purpose is to refuse a malformed order with HTTP 400 without costing a queue hop and a wait.

## Why the deadline is written down rather than inferred

`deadline_at` is the moment the waiting worker gives up, written by the worker that knows its own timeout. The engine needs it so that a restart does not fire a stale order into a market that has moved: an intent whose deadline is long past is recorded and answered rather than placed.

It could have been recomputed in the engine from `created_at` plus the engine's own reading of the timeout setting. That would be wrong whenever the two processes disagree about the setting, which is exactly the situation a restart after a configuration change creates.

## Why `synthetic_type` is read here but not checked here

The type is read off the body so that the stream entry says what kind of order it is without anyone having to parse the body again, which matters for reading a backlog by hand. It is deliberately not validated: what a bracket needs beside its type, and whether those values make sense together, is the bracket's own business and is checked where the engine builds one. Validating it in two places would mean two lists of legal types to keep in step.

## Why plain limit orders are held by default, and decided here

The user asked for the place route to behave as they remembered the old order manager: an order goes to a broker only once it could realistically fill. On `main` that only happened for an order that asked for `virtual_limit` while the API ran in engine mode; direct mode, the default, sent everything at once. `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS`, on by default, makes a plain limit order a `virtual_limit`.

The decision is made where the intent is built, in the API worker, so the intent on the stream, the parent's `synthetic_type` and the answer all name the type that actually runs. Only a `DAY` limit with its own `price` and no `synthetic` object is held. An `IOC` order means "now or never", which holding would change; a limit priced only by `price_reference` cannot be held, because `VirtualLimit` holds at the body's own price; and a body that names any type, `simple` included, has chosen, which is how a caller opts out and how flatten's closing orders stay immediate.

The offline route suites pin the setting off, because their scenarios test sending at once; `order_engine_changes` turns it on for the scenarios about holding.

## Why an after-market order is never held

An after-market order is queued by the broker for the next session's open. Nothing about the current quote says when it could fill, and outside market hours no fresh quote arrives to release it, so holding it meant it was never sent at all. A live test through tradingmachine on 2026-09-27 confirmed this: every after-market limit order came back `armed` and none reached a broker. `is_after_market` reads the flag with the same spellings `OrderRequest.parse_flag` accepts, so a body the route treats as after-market is never held. The scenario `a_plain_limit_order_is_held_by_default_and_nothing_else_is` in `test_runs/order_engine_changes.py` places one and records it being sent at once.
