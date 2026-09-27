# Notes on `test_runs/order_engine_throughput.py`

## Why it checks rather than records

The other engine suites compare against a recording, because what they check is exact behaviour. Throughput is a timing, and a timing varies from run to run, so this suite checks properties that hold on every run instead: every order accepted, the rate budget never admitting more than 10 messages to one broker in any one second, ten workers reaching at least 80 orders a second across ten brokers, and ten workers beating one.

## What it measured when it was written

On 2026-09-27, with ten stub brokers answering after 200 ms and 30 orders per broker:

| Workers per broker | Time for 300 orders | Average orders a second | Most admitted to one broker in one second |
|---|---|---|---|
| 1 | 6.04 s | 49.7 | 5 |
| 10 | 2.24 s | 133.7 | 10 |

One worker does five orders a second at one broker, which is all a thread can do when each call takes a fifth of a second. Ten workers are held by the rate budget instead, at 10 a second each. The average above 100 is the burst at the start: each broker takes a full ten in its first second, so 30 orders go out at 0, 1 and 2 seconds and finish at about 2.2.

## Why the budget is checked at admission and arrivals only reported

The rate window counts a message when it gives it room, and the stub broker sees the request a few milliseconds later, after the worker builds and sends it. In two runs of six the stub saw eleven requests within one second, because thread scheduling delayed one request more than its neighbour, while the window had admitted exactly ten. The check is on the admission times the fake script logs, which is the moment the limit is kept at; the arrival count is printed alongside so the effect stays visible. `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WINDOW_SECONDS` exists so a margin can be set for it.

## Two stand-in faults this suite found

The first version found two faults in the shared test stand-ins, both invisible to suites that never write more than ten intents or run more than one thread. The fake `XREADGROUP` marked every new entry delivered but returned only `count` of them, so a burst larger than one read lost the rest. The fake rate window script ran without a lock, so two threads could both find room for a tenth message and admit eleven, which the real Redis, running a script as one step, never does.
