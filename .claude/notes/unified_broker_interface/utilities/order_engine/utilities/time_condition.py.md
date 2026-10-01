# Notes on `unified_broker_interface/utilities/order_engine/utilities/time_condition.py`

## Why the moment is worked out once, when the plan is placed

`prepare` resolves the time with `Moments.time_on_trading_day`, as the `scheduled` type does, and keeps the epoch in the part's memory, which is recorded with `record_parameters`. A time that has passed on a trading day is then refused at placement with 400, while the caller is still waiting for an answer, rather than being discovered later. A weekend or holiday rolls to the next trading day.

## Why `time_at` and `time_after` behave the same

Both hold from the time onwards. `time_at` is kept because it reads naturally for "place it at 10:00", and `time_after` because it reads naturally inside `all`. `time_before` is the only one with a different meaning.

## Why time conditions are checked on price ticks

`PlanOrder` sets `WANTS_PRICES` and not `WANTS_CLOCK`, so a plan with only a time trigger is still offered a tick every second through the price ticker, which calls every price-watching parent whether or not a quote arrived. That avoids asking every plan on two tickers. If the price ticker stops, a time trigger stops too; `WANTS_CLOCK` can be added if that proves a problem.

## `time_from` (2026-10-01)

`time_at` refuses a time already passed on a trading day, which is right for a scheduled order. The closing price order wants the opposite: placed inside its window, it starts at once. `time_from` holds at once in that case.
