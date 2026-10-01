# Notes on `unified_broker_interface/utilities/order_engine/utilities/lifetime.py`

## Why it copies the good-till-time and time-stop rules

`at_time` on the next trading day, minutes counted from placing and refused on a day that does not trade, cancelling what rests while keeping what filled, making the rest marketable two ticks past the touch, and cancelling before closing what filled at market are the rules of `good_till_time.py` and `time_stop.py`. The offline scenarios `a_plan_good_till_time_*`, `a_plan_limit_then_market_*` and `a_plan_time_stop_*` send the same requests as today's.

Two differences are deliberate. A plan that cancels at its time ends the parent when the broker confirms the cancel, as every plan order does, where today's type records `cancelled` as soon as it asks. Today's answer carries `cancel_at`; a plan answers with the broker's answer as it is, and the end time is in the part's record as `ends_at`.

## What is not built

`after_days` would have a plan outlive the trading day. Recovery carries parents overnight by type, through `CARRIES_OVERNIGHT`, and marking every plan as carried would bring back yesterday's waiting plans and let them fire, which today's 06:00 expiry of the parent caches prevents. Carrying one plan and not another needs recovery to ask each parent, so `after_days`, and with it a preset for the `gtt` type, waits for that change. `when` ends an order on any condition and comes with the account conditions in stage 5.

## Why `ends_at` takes a moment

`Moments` already takes the moment to reckon from, and passing it through lets the example programs work out ends from a fixed Wednesday and a fixed Sunday, so their output does not change from day to day.

## `after_days` (2026-10-01)

Built once recovery could carry one plan overnight without carrying them all. It counts whole days of 24 hours from placing, as today's gtt counts `valid_days`, not trading days. Only `when` is still unbuilt, waiting for the account conditions.

## `when` (2026-10-01)

Built with the account condition. A lifetime ending `when` has no moment to work out, so `ends_at` is None and the plan marks the part's record `ends_when`; the condition is asked on every tick, with its memory kept as `lifetime_memory`.
