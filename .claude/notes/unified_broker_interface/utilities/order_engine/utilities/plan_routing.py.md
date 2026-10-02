# plan_routing.py

## Why a setting, empty by default (2026-10-02)

The design's switch-over moves each fixed type to its preset only after that preset has traded live, one name at a time. Building the routing now and leaving the setting empty lets the code be reviewed and tested before Monday's live tests, while changing nothing in production until a name is added. An unknown name stops the engine at start, as an unknown broker selector does, because a misspelt name silently routing nothing would leave the operator believing a type had moved.

## Where it is applied

`OrderEngine.synthetic_order` rewrites the intent before it looks up the class, so the parent is recorded as a `plan` from its first event. Recovery, the tickers and the follower look parents up by their recorded type, so a routed parent keeps running as a plan after a restart even if the setting is later emptied, and a fixed-type parent placed before a name was added keeps running as the fixed type.

## `gtt`

Every fixed type's preset has the type's own name except `gtt`, whose preset was named `good_till_triggered`; `PRESET_NAMES_BY_TYPE` holds that one exception rather than renaming either.

## The offline suite

The suite pins the setting to empty around every scenario, as it pins the broker settings, so a value in `.env` cannot change the recordings; `run_plan_routing_checks` turns it on around today's grid, bracket and market-if-touched bodies, whose broker requests match the fixed types' recordings.

## The order flags stay beside the plan, since 2026-10-02

`closes_position` and `reduce_only` can be given on any synthetic type, and both are read from the top of the parent's parameters: `SyntheticOrder.closes_position` in `base.py` and `ReduceOnlyCheck.is_asked_for` in `reduce_only.py`, which `PlanOrder` runs too. `routed` first copied every key of the caller's `synthetic` object except `type` into the preset's settings, and no preset lists either flag, so a routed order carrying one was refused with HTTP 400 `unknown_setting`, such as `the market_if_touched preset takes trigger_price, trigger_direction, trigger_on, hold_seconds, buffer_ticks, not 'closes_position'`. That broke the switch-over's promise that the caller's request does not change, and it would have failed every `square_off` order from tradingmachine, whose `SquareOffOrder` sends `closes_position` by default. `routed` now takes the two flags out of the settings and keeps them at the top of the plan's `synthetic` object, where the plan reads them as every fixed type does. The audit from tradingmachine that found it is recorded in that project's notes.

`run_plan_routing_checks` gained two scenarios, a routed `market_if_touched` order with `closes_position` and one with `reduce_only`. Before the change both answered 400; after it the first is armed and places its order at the touch, and the second is armed and places nothing at the touch, because the scripted account holds no position for it to reduce.
