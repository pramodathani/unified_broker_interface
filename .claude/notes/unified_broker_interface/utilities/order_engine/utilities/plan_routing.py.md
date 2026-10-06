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

## Every type routed, the setting removed (2026-10-03)

The fixed classes were retired on 2026-10-03, so the switch-over is complete: every type in `ROUTED_TYPES` (52 names, written out rather than read from the registry, which now holds only `simple` and `plan`) is always rewritten into a plan of its preset, and `UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES` is no longer read. A `.env` that still sets it changes nothing. Before retiring them, the offline engine suite was run twice in one session, once as the fixed classes and once with every type routed and holding off: every scenario sent the same broker requests, except a basket naming one instrument twice (the classes refused it; the preset now refuses it again, by the user's choice) and protective orders with no position held, which the plan refuses with `protect_needs_position` (kept, by the user's choice). Answers differ in form (plan `legs` and wording, `working` for `protecting`, plan paths as leg roles); `timing_ms` was added back to multi-order plan answers.

`check_unrouted` now only concerns `simple`, the one type sent at once by definition. The sections above about an empty setting, the suite pinning it and fixed-type parents running on are history; recovery now warns about an open parent of a retired type (`EngineRecovery.warn_if_unrun`).

## The configured cost guard (2026-10-07)

`UNIFIED_BROKER_INTERFACE_API_ORDER_MAXIMUM_COST_BPS` is applied here, when the intent is routed, rather than in `PresetExpander`, for the same reason as `hold_limits`: the value is written into the order when it arrives, so a restart reads the order the same way even if the setting has changed since. It is given only to a `marketable_limit` that does not set its own. `0` or empty means off, through `float(... or '0') or None` in `utilities/configurations.py`.
