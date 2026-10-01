# Notes on `unified_broker_interface/utilities/order_engine/utilities/repeat_part.py`

## Why copies rather than a loop

A plan's parts are built afresh from the plan on every event, and every part needs a fixed path so its broker orders can be told apart and replayed after a restart. A Repeat that ran one child again would have to invent paths and remember how many runs it had made. Reading `times` copies up front gives each run a path and a record of its own, `root.children.<n>`, and lets the together join run them; `MOST_REPEATS` is 100, today's accumulation limit, so a plan never holds more than a hundred copies.

## The schedule

Each copy after the first gets an `ElapsedCondition` of `every_minutes × n`, joined with `all` to any trigger it already has. The moments are worked out when the plan is placed, as today's accumulation counts from placing, and kept in each copy's trigger memory, recorded with the received event. They need no prices, so clock ticks send the copies on time.

## Not built

`every_trading_day_at` and `until` need a plan to outlive the trading day, as `after_days` lifetimes do, and wait for the same recovery change; today's daily stop and scale with profit taker are not presets yet for that reason.
