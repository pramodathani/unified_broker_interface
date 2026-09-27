# Notes on `unified_broker_interface/utilities/order_engine/intent_handoff.py`

## Why the worker waits rather than answering something to poll

The whole promise of the engine is that a caller cannot tell which process placed the order. `POST /api/orders/place` answers one request with one outcome today, and a caller that had to poll for the result would be a different API, which every existing client would have to be changed for.

What the wait costs is one pooled Redis connection held for as long as the engine takes. That is the same shape as the cost the direct path already pays, where a worker holds a broker connection for as long as the broker takes, and the timeout bounds it. `get_cache()` sets no socket timeout, which is what makes a blocking `BLPOP` safe here.

## Why a stream for the intent and a list for the answer

They are asymmetric on purpose.

The intent goes on a stream because it has to survive an engine that is not running. A restarting engine reads what was written while it was down, and a backlog can be inspected with `XINFO GROUPS` exactly like every other queue in this project. A list would lose the consumer group and with it any way of seeing how far behind the engine is.

The answer goes on a list because a string cannot be blocked on, and blocking is the point. `BLPOP` takes the answer and empties the key in one step, so the key removes itself in the ordinary case and the TTL only ever expires an answer nobody came back for.

## Why everything after the intent is written answers `unknown`

There are two ways to fail once the intent is on the stream: the wait runs out, and Redis stops answering during the wait. Both were originally handled differently, the second as a refusal with HTTP 503. That was wrong and was corrected before the behaviour was recorded.

HTTP 503 tells a caller that the request did not happen, and a caller acting on that will retry. But the intent is already on the stream, so the engine may well place it, and the retry becomes a second live order. Outcome `unknown` with HTTP 504 is the only answer that is true in both cases, and it is what `BrokerAnswer.OUTCOME_STATUSES` already means by it: read the order book before retrying.

The engine keeps the other half of that promise, by refusing to place an intent whose deadline passed more than `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` ago.

## Why `preparation` is recomputed

`time.perf_counter()` counts from an arbitrary origin that differs between processes, so the engine's own `preparation` cannot be compared with anything this worker measured. The worker therefore replaces it with the time it measured itself, less the broker time the engine reported.

What the caller is told the field means does not change: the API's own work before the request left the machine. In engine mode that work now includes the queue hop and the engine's preparation, and including them is correct, because all of it happened before the request left. The finer split belongs in the engine's own event log, where someone diagnosing a slow order will look, rather than in an answer whose shape every client depends on.

## Why the API resolves the instrument and the engine does not

The engine repeats most of the Redis reads the place route makes, because it has to build a broker request of its own. The question was whether it should repeat the instrument lookup as well.

It does not. The route resolves the instrument and writes the id into the intent. The reason is that the lookup is not a read but a rule: no match is HTTP 404, and more than one match is HTTP 400 telling the caller to give an `instrument_id` instead. Copying thirty-six lines of that rule into the daemon would mean a future correction has to be made twice, and would eventually be made once.

What remains duplicated is about sixty-eight lines of pipeline sequencing, which is I/O ordering rather than a rule, and which the two processes are entitled to differ on: the engine has no access token to check and reads no warm identifier for a cache it does not keep.

The engine still reads the instrument's own catalogue entry, because it needs the order handles and the contract size at the moment it places each leg, and a bracket's stop may be placed minutes after its entry.

The cost is one extra Redis round trip in engine mode for an order that names identity fields rather than an id, which the recording shows as four round trips against three. That round trip is one the route already makes in direct mode, so nothing new was added; it simply now happens before the handoff rather than after it.

## Why a list shares one reply key

`place_many` writes every intent of a list in one pipeline and gives them all one reply list, `unified:orders:intents:reply:<request_id>`, with each answer naming its `request_index`. One key lets the API worker wait with a single `BLPOP` at a time for whichever order the engine's lanes finish next, rather than polling one key per order in turn, which would wait on the slowest broker's order before seeing the fast ones.

A single order keeps its own `unified:orders:intents:result:<intent_id>` list and its answer carries no `request_index`, so the single form and its recordings did not change.

## Why a failed pipeline answers every order unknown

The intents are written in one pipeline that is not a transaction, so a Redis failure part way through can leave some intents on the stream and not others. Nothing here can tell which, and the engine may place the ones that got through, so every order of the list is answered as outcome `unknown` with its `intent_id` rather than refused.

## Why every answer is stored under its intent id

A list can take longer than any one HTTP request should wait, and the wait is capped below gunicorn's worker timeout, so some orders may be answered only after the caller has been told `unknown`. The engine stores every answer at `unified:orders:intents:answer:<intent_id>`, with `SET NX` so a later 409 for a repeated intent never replaces the first answer, and `GET /api/orders/intents/<intent_id>` reads it back. It costs no extra round trip, since the write rides in the pipeline that pushes the reply.
