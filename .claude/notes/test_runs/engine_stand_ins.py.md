# Notes on `test_runs/engine_stand_ins.py`

## Why an engine runs inside `BLPOP`

With direct placement removed, the place route never calls a broker itself: it writes an intent and waits. The route suites could have stubbed the engine's answer, as `order_engine_routes` does, but then nothing would check the ten brokers' place requests any more, which were the bulk of what `order_routes` recorded.

`InlineEngine` runs the real `OrderEngine`, without lanes, over the waiting intents at the moment the route calls `BLPOP` on an empty reply list. Everything happens on one thread in a fixed order, so the recordings stay repeatable, and the stubbed brokers see exactly the requests the engine builds. The engine's own Redis round trips are subtracted, and it can never be the round trip a scenario makes fail, so a recording keeps counting only the route's work and a scenario that fails the route's third round trip still fails the route's.

## Why the route suites count UUIDs now

The route suites used to replace `uuid.uuid4` with one constant. Through the engine, the intent id and the parent id come from `uuid.uuid4` too, and the engine refuses an intent whose id already started a parent, so the second request of a multi-step scenario was answered as a repeat. `CountingUuid` gives each call its own value, the same on every run, and is reset before each scenario.
