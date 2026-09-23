# `vwap.py`

## Why the default profile is a shape rather than a measurement

The proper implementation reads this instrument's own measured intraday volume history out of TimescaleDB. That was not done, and the reason is worth recording rather than leaving as an omission somebody rediscovers.

The engine reads Redis on every tick and PostgreSQL only when it writes an event. Adding a history query — with a warm-up, a fallback for an instrument with no history, and a decision about how many days to average — would put a second data source inside the order path for a number that only changes the sizes of a handful of slices.

So the default is the ordinary Indian equity day: heavy in the first half hour, quiet across lunch, heavy again into the close, with the last bucket as large as the first because it is fifteen minutes rather than thirty. It is a good approximation for a liquid stock and a poor one for anything with its own rhythm — a commodity that wakes when a foreign market opens, an option that only trades around its strike. `volume_profile` lets somebody who has measured their instrument pass the real thing, which is the escape hatch that makes the approximation acceptable.

## Why the clock stays even

Only the sizes are weighted. The slices still go out at even intervals, which keeps the schedule visible in advance and keeps this a small subclass of the timed order rather than a second scheduler with its own bugs.

A more sophisticated build would also bunch the slices in time. The gain would be small next to the gain from sizing them, and the cost would be a second thing to reason about when a slice does not go out when expected.
