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
