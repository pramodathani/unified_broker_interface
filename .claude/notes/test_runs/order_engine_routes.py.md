# Notes on `test_runs/order_engine_routes.py`

## Why this is a second file and a second recording

`--record` rewrites a whole fixture unconditionally, with no diff and no confirmation. `test_runs/fixtures/order_routes.jsonl` is the evidence that moving order placement out of the blueprint changed nothing about the direct path, and it is the regression guard for the whole order engine branch. Recording engine scenarios into it would rewrite that evidence, and the rewrite would look exactly like a successful run.

So the engine scenarios have their own entry point and their own fixture. The cost is a second `record`, `compare` and `read_recording`, which are near copies of the originals. That duplication is deliberate and is cheaper than the alternative, which is one suite whose `--record` can destroy the thing it is supposed to protect.

## What is reused rather than copied

The Redis stand-in, the starting Redis contents, the broker network stub and the request body builders all come from `test_runs/order_routes.py`. `FakeEngineRedis` subclasses `FakeRedis` and adds only `xadd` and `blpop`, so an engine-mode order is recorded against the same instruments, logins, settings and order books as the direct path.

## Why `blpop` never blocks

The stand-in answers with whatever was seeded onto the reply list, or with None, which is what a real wait that ran out returns. A scenario therefore exercises the timeout path in no time at all, rather than the five seconds a real wait would take. There is nothing to synchronise, because the suite is single threaded: the answer the engine "would have" pushed is put on the list before the request is sent.

The reply key names the intent, which is not built until the request runs. That works because `uuid.uuid4` is replaced for the whole run, so the key is known in advance.

## What cannot be recorded, and what is recorded instead

An intent carries three values that differ on every run: `created_at` and `deadline_at` are clock readings, and `api_worker` names this host and process. They are left out, and the list of what was left out is recorded beside the intent so the omission is visible rather than silent.

What they are for is still checked. The gap between the two times is recorded as `timeout_seconds`, which pins that the deadline written for the engine matches the wait the worker actually performs. That is the value the engine uses to decide an intent is too old to place, so a disagreement between them would let a stale order through.

## The two numbers worth watching in the recording

`redis_round_trips` is three for an engine-mode order: the first pipeline, the `XADD` and the `BLPOP`. If it becomes four, something has added a read on the order path.

`intents` is zero for the scenarios named `an_invalid_body_is_never_queued` and `a_bad_token_is_never_queued`. Those two are the proof that a malformed body and a bad token are still refused by the worker without costing a queue hop, which is the reason the branch sits after validation rather than before it.
