# Notes on `test_runs/instrument_routes.py`

## Why this suite exists

Nothing drove the instrument routes offline before it. It was written first, against the code as it stood, so that letting the routes accept a list of instruments could be checked against a recording of what the single-instrument routes did. The single `GET` scenarios are that proof: they were recorded before any route code changed, and a refactor of the catalogue, the quote service or the history module must leave them unchanged.

## Why it has its own fixture

`--record` rewrites a whole file, for the same reason given in `order_engine_routes.py.md`. Recording these scenarios into `order_routes.jsonl` would rewrite the evidence for the order routes.

## How the services are stood in for

The blueprint builds its mapping cache, catalogue and quote service lazily in `_services()`. The suite sets those three attributes itself before the first request, so `_services()` finds them built and never opens a real Redis client or engine.

- **Redis.** The mapping cache takes a `MappingRedisConnection(client=...)`, so the same in-memory stand-in serves the blueprint's own client (token check, quote cache, candle cache) and the mapping cache's client. Every round trip on either is counted together, which is what the recorded `redis_round_trips` means.
- **Redis contents.** Identities, catalogue members, seen dates, handles and attributes are written through the real `MappingRedisTier` encoders rather than typed out as JSON, so the stand-in holds exactly what the daily warm would write. The tier is built around a placeholder client because the encoders never touch it.
- **Postgres.** `TickEngine` answers only a query against `unified.ticks` or `unified.ticks_adjusted` and raises on anything else. A scenario that reaches the database unexpectedly, such as a cold-cache fallback, therefore shows up as a 500 in the recording rather than as a silent pass. `tick_queries` counts the tick queries run.
- **Brokers.** `QuoteService._from_broker` is replaced on the instance by `ScriptedBrokers.from_broker`. That skips the real fetch, normalisation and resolver plan check, which belong to each broker's quote module and to the tick layer, and keeps what the route and the service decide: whether a broker is asked at all, which brokers in which order, and what happens when they fail. Calls are recorded sorted, because a batch asks for quotes on several threads and the order they finish in is not fixed.
- **Clock.** The quote service reads `time.time()` to decide whether a cached quote is fresh. The suite replaces the module's `time` name with `FixedClock`, pinned to 10:00 IST on the mapping date, which is inside the NSE session, so an hour-old quote counts as stale and a one-minute-old one as fresh.

## What each blueprint build costs

A fresh blueprint and a fresh mapping cache are built per scenario. The mapping cache remembers the current mapping date for five minutes, so reusing one across scenarios would make the first scenario pay one more round trip than the rest, and the recorded counts would depend on scenario order.

## What is not covered

The Postgres fallbacks (a past `date`, a cold cache, the history of an instrument no longer mapped) are not driven, because they need SQL answers the stand-in engine does not give. `/prices` is driven only from its Redis copy. The `days` form of `/prices` is not driven, because it reads `date.today()`.
