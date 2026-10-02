# plan_routing.py

## Why a setting, empty by default (2026-10-02)

The design's switch-over moves each fixed type to its preset only after that preset has traded live, one name at a time. Building the routing now and leaving the setting empty lets the code be reviewed and tested before Monday's live tests, while changing nothing in production until a name is added. An unknown name stops the engine at start, as an unknown broker selector does, because a misspelt name silently routing nothing would leave the operator believing a type had moved.

## Where it is applied

`OrderEngine.synthetic_order` rewrites the intent before it looks up the class, so the parent is recorded as a `plan` from its first event. Recovery, the tickers and the follower look parents up by their recorded type, so a routed parent keeps running as a plan after a restart even if the setting is later emptied, and a fixed-type parent placed before a name was added keeps running as the fixed type.

## `gtt`

Every fixed type's preset has the type's own name except `gtt`, whose preset was named `good_till_triggered`; `PRESET_NAMES_BY_TYPE` holds that one exception rather than renaming either.

## The offline suite

The suite pins the setting to empty around every scenario, as it pins the broker settings, so a value in `.env` cannot change the recordings; `run_plan_routing_checks` turns it on around today's grid, bracket and market-if-touched bodies, whose broker requests match the fixed types' recordings.
