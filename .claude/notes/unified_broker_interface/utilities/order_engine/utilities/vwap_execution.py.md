# Notes on `unified_broker_interface/utilities/order_engine/utilities/vwap_execution.py`

## Why it is so short

Everything but the weights is in `TimedSlicesExecution`; see that file's note. The weights copy today's type exactly, so the preset sends what the type sends.

## The segment's own open (2026-10-02)

`begin` records `opens_at` and `equity` in the execution memory from `SessionOpen`, so the weights survive a restart without another catalogue read, and `profile_given` tells a caller's profile from the equity default. A plan that started before this change has neither key and keeps the equity behaviour it began with. The only change to existing recordings was those two keys appearing in the memory; slice quantities were identical.
